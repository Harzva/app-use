import ApplicationServices
import Cocoa
import Foundation
import WebKit

private func resolveRepoRoot() -> URL {
    let fm = FileManager.default
    if let envRoot = ProcessInfo.processInfo.environment["WECHAT_ECOSYSTEM_REPO_ROOT"],
       !envRoot.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        return URL(fileURLWithPath: envRoot)
    }
    if let resUrl = Bundle.main.resourceURL {
        let marker = resUrl.appendingPathComponent("repo_root.txt")
        if let raw = try? String(contentsOf: marker, encoding: .utf8) {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                // Avoid stat'ing /Volumes/* removable volumes from an internal /Users/*/Applications/*.app at startup
                if trimmed.hasPrefix("/Volumes/") || fm.fileExists(atPath: trimmed) {
                    return URL(fileURLWithPath: trimmed)
                }
            }
        }
    }
    let exeUrl = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
    let runningOnRemovableVolume = exeUrl.path.hasPrefix("/Volumes/")
    if runningOnRemovableVolume {
        let binDir = exeUrl.deletingLastPathComponent()
        let maybeRepo = binDir.deletingLastPathComponent()
        if fm.fileExists(atPath: maybeRepo.appendingPathComponent("bin/wechat-bot").path) {
            return maybeRepo
        }
        var cursor = exeUrl
        for _ in 0..<5 {
            cursor = cursor.deletingLastPathComponent()
            if cursor.path == "/Volumes" || cursor.path == "/" { break }
            if fm.fileExists(atPath: cursor.appendingPathComponent("bin/wechat-bot").path) {
                return cursor
            }
        }
    }
    return URL(fileURLWithPath: fm.currentDirectoryPath)
}

private func resolveVisionAxBinary(repoRoot: URL) -> URL? {
    let fm = FileManager.default
    if let exeDir = Bundle.main.executableURL?.deletingLastPathComponent() {
        let bundled = exeDir.appendingPathComponent("wechat-vision-ax")
        if fm.isExecutableFile(atPath: bundled.path) {
            return bundled
        }
    }
    let exeUrl = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
    let sibling = exeUrl.deletingLastPathComponent().appendingPathComponent("wechat-vision-ax")
    if fm.isExecutableFile(atPath: sibling.path) {
        return sibling
    }
    let fallback = repoRoot.appendingPathComponent("bin/wechat-vision-ax")
    if exeUrl.path.hasPrefix("/Volumes/") || !fallback.path.hasPrefix("/Volumes/") {
        if fm.isExecutableFile(atPath: fallback.path) {
            return fallback
        }
    }
    return nil
}

private func consoleVersion(_ baseUrl: String) -> String? {
    guard let url = URL(string: "\(baseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/health") else {
        return nil
    }
    let sem = DispatchSemaphore(value: 0)
    var version: String?
    var req = URLRequest(url: url)
    req.timeoutInterval = 1.2
    URLSession.shared.dataTask(with: req) { data, resp, _ in
        if let http = resp as? HTTPURLResponse, http.statusCode == 200,
           let d = data,
           let obj = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] {
            version = obj["version"] as? String
        }
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + 2.0)
    return version
}

private func stopStaleConsole(repoRoot: URL) {
    // 版本感知升级：App 更新后，旧版本 console 可能仍占着 18788——按 pidfile 停掉旧进程
    var pidfileCandidates: [URL] = []
    // bundle 外稳定位置（与 mcp_server.serve_http 一致）
    pidfileCandidates.append(URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support/WeChatBot/console.pid"))
    if let resUrl = Bundle.main.resourceURL {
        pidfileCandidates.append(resUrl.appendingPathComponent("logs/console.pid")) // 兼容旧位置
    }
    pidfileCandidates.append(repoRoot.appendingPathComponent("logs/console.pid"))
    var killed = 0
    for candidate in pidfileCandidates {
        if let raw = try? String(contentsOf: candidate, encoding: .utf8),
           let pid = Int(raw.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1 {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/kill")
            proc.arguments = [String(pid)]
            try? proc.run()
            proc.waitUntilExit()
            killed += 1
            backendFailureLog("stopStaleConsole: killed stale console pid \(pid) (version mismatch)")
        }
    }
    if killed == 0 {
        // 兜底：更老的 console 没写 pidfile——按端口找到占用进程再停
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        proc.arguments = ["-ti", "tcp:18788"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        try? proc.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        let text = String(data: data, encoding: .utf8) ?? ""
        for pidText in text.split(separator: "\n") {
            if let pid = Int(pidText.trimmingCharacters(in: .whitespaces)), pid > 1, pid != ProcessInfo.processInfo.processIdentifier {
                let kill = Process()
                kill.executableURL = URL(fileURLWithPath: "/usr/bin/kill")
                kill.arguments = [String(pid)]
                try? kill.run()
                kill.waitUntilExit()
                killed += 1
                backendFailureLog("stopStaleConsole: killed stale console pid \(pid) via lsof fallback")
            }
        }
    }
}

private func isConsoleHealthy(_ baseUrl: String) -> Bool {
    guard let url = URL(string: "\(baseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/health") else {
        return false
    }
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    var req = URLRequest(url: url)
    req.timeoutInterval = 1.2
    URLSession.shared.dataTask(with: req) { data, resp, _ in
        if let http = resp as? HTTPURLResponse, http.statusCode == 200,
           let d = data, let text = String(data: d, encoding: .utf8), text.contains("\"ok\"") {
            ok = true
        }
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + 1.5)
    return ok
}

private func backendFailureLog(_ message: String) {
    // 静默失败可见化：排障时有迹可循（~/Library/Logs/wechat-bot-backend.log）
    let logPath = NSHomeDirectory() + "/Library/Logs/wechat-bot-backend.log"
    let line = "\(Date()) \(message)\n"
    if let handle = FileHandle(forWritingAtPath: logPath) {
        handle.seekToEndOfFile()
        handle.write(line.data(using: .utf8)!)
        try? handle.close()
    } else {
        try? line.write(toFile: logPath, atomically: true, encoding: .utf8)
    }
}

private func ensureBackendRunning(repoRoot: URL, consoleUrl: String) {
    if isConsoleHealthy(consoleUrl) {
        // 版本感知：旧 console 还在跑旧代码（App 更新后常见占坑），停旧起新
        let running = consoleVersion(consoleUrl)
        let expected = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        if running == expected || running == nil || expected.isEmpty {
            return
        }
        backendFailureLog("ensureBackendRunning: console version \(running ?? "?") != app \(expected), restarting backend")
        stopStaleConsole(repoRoot: repoRoot)
        for _ in 0..<25 { // 等端口释放
            if !isConsoleHealthy(consoleUrl) { break }
            Thread.sleep(forTimeInterval: 0.2)
        }
    }
    // App 内 bin 优先（安装版自足，不依赖 repo_root 指向的源码目录），开发环境回退 repoRoot
    var candidates: [URL] = []
    if let resUrl = Bundle.main.resourceURL {
        candidates.append(resUrl.appendingPathComponent("bin/wechat-bot"))
    }
    candidates.append(repoRoot.appendingPathComponent("bin/wechat-bot"))
    let botBin = candidates.first { FileManager.default.isExecutableFile(atPath: $0.path) }
    guard let launcher = botBin else {
        backendFailureLog("ensureBackendRunning: 未找到可执行的 wechat-bot 启动器（已尝试 App 内 Resources/bin 与 repoRoot/bin）")
        return
    }
    let proc = Process()
    proc.executableURL = launcher
    proc.arguments = ["console", "--host", "127.0.0.1", "--port", "18788"]
    proc.currentDirectoryURL = launcher.deletingLastPathComponent().deletingLastPathComponent() // App Resources（避免 cwd 源码遮蔽包内代码）
    proc.standardOutput = FileHandle.nullDevice
    proc.standardError = FileHandle.nullDevice
    try? proc.run()
    for _ in 0..<15 {
        if isConsoleHealthy(consoleUrl) {
            break
        }
        Thread.sleep(forTimeInterval: 0.2)
    }
}

// MARK: - HarvisBar-Style WeChat Sidebar Dock Geometry & Window Probe

enum WeChatDockSide: String {
    case right = "dock_right"
    case left = "dock_left"
    case overlayRight = "overlay_right" // Legacy verification token; never used for automatic docking.
    case standalone = "standalone"
}

struct WeChatTargetWindow {
    let windowID: CGWindowID
    let ownerPID: pid_t
    let title: String
    let appKitFrame: NSRect
    let quartzFrame: CGRect
}

struct WeChatDockPlan {
    let side: WeChatDockSide
    let sidebarFrame: NSRect
    let tiledWeChatQuartzFrame: CGRect?
}

struct WeChatDockGeometry {
    static let defaultSidebarWidth: CGFloat = 430
    static let minimumSidebarWidth: CGFloat = 360
    static let collapsedSidebarWidth: CGFloat = 56
    static let cornerFillOverlap: CGFloat = 0
    static let dockGap: CGFloat = 10

    static var mainDisplayTop: CGFloat {
        NSScreen.screens
            .first { $0.frame.contains(NSPoint.zero) }?
            .frame.maxY ?? NSScreen.main?.frame.maxY ?? 1440
    }

    static func appKitFrame(quartzOrigin: CGPoint, size: CGSize, mainDisplayTop: CGFloat) -> NSRect {
        NSRect(
            x: quartzOrigin.x,
            y: mainDisplayTop - quartzOrigin.y - size.height,
            width: size.width,
            height: size.height
        )
    }

    static func quartzFrame(appKitFrame: NSRect, mainDisplayTop: CGFloat) -> CGRect {
        CGRect(
            x: appKitFrame.minX,
            y: mainDisplayTop - appKitFrame.maxY,
            width: appKitFrame.width,
            height: appKitFrame.height
        )
    }

    static func screenContaining(_ frame: NSRect) -> NSScreen? {
        let mid = NSPoint(x: frame.midX, y: frame.midY)
        return NSScreen.screens.first { NSMouseInRect(mid, $0.frame, false) }
            ?? NSScreen.screens.max {
                let a = NSIntersectionRect($0.frame, frame)
                let b = NSIntersectionRect($1.frame, frame)
                return a.width * a.height < b.width * b.height
            }
            ?? NSScreen.main
    }

    static func findWeChatMainWindow(windowID: CGWindowID? = nil, ownerPID expectedOwnerPID: pid_t? = nil) -> WeChatTargetWindow? {
        let wechatApp = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.xinWeChat").first
            ?? NSWorkspace.shared.runningApplications.first {
                let n = $0.localizedName ?? ""
                return n == "微信" || n == "WeChat"
            }
        let targetPID = wechatApp?.processIdentifier
        guard let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }

        let top = mainDisplayTop
        var best: (WeChatTargetWindow, Double)? = nil
        for row in rows {
            guard (row[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
                  (row[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue != false,
                  let ownerPID = (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
                  let num = row[kCGWindowNumber as String] as? NSNumber,
                  let bounds = row[kCGWindowBounds as String] as? NSDictionary,
                  let qFrame = CGRect(dictionaryRepresentation: bounds),
                  qFrame.width >= 420, qFrame.height >= 320 else {
                continue
            }
            let ownerName = row[kCGWindowOwnerName as String] as? String ?? ""
            let pidMatches = (targetPID != nil && pid_t(ownerPID) == targetPID)
            let nameMatches = (ownerName == "微信" || ownerName == "WeChat")
            guard targetPID != nil ? pidMatches : nameMatches else { continue }

            if let windowID, num.uint32Value != windowID { continue }
            if let expectedOwnerPID, ownerPID != expectedOwnerPID { continue }
            let title = row[kCGWindowName as String] as? String ?? ""
            var score = Double(qFrame.width * qFrame.height)
            if title == "微信" || title == "WeChat" {
                score += 20_000_000
            }
            let akFrame = appKitFrame(quartzOrigin: qFrame.origin, size: qFrame.size, mainDisplayTop: top)
            let candidate = WeChatTargetWindow(
                windowID: CGWindowID(num.uint32Value),
                ownerPID: pid_t(ownerPID),
                title: title,
                appKitFrame: akFrame,
                quartzFrame: qFrame
            )
            if best == nil || score > best!.1 {
                best = (candidate, score)
            }
        }
        return best?.0
    }

    static func computeDockPlan(
        wechatFrame: NSRect,
        desiredWidth: CGFloat,
        collapsed: Bool = false,
        preferredSide: WeChatDockSide? = nil,
        visibleFrame: NSRect? = nil
    ) -> WeChatDockPlan {
        let visible = visibleFrame ?? screenContaining(wechatFrame)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1920, height: 1050)
        let width = min(visible.width, collapsed ? collapsedSidebarWidth : max(minimumSidebarWidth, desiredWidth))
        let requiredWidth = collapsed ? collapsedSidebarWidth : minimumSidebarWidth
        let height = min(max(360, wechatFrame.height), visible.height)
        let y = min(max(wechatFrame.minY, visible.minY), visible.maxY - height)
        let rightRoom = visible.maxX - wechatFrame.maxX - dockGap
        let leftRoom = wechatFrame.minX - visible.minX - dockGap
        let sides: [WeChatDockSide] = preferredSide == .left ? [.left, .right] : [.right, .left]
        for side in sides {
            let room = side == .right ? rightRoom : leftRoom
            guard room >= requiredWidth else { continue }
            let fitWidth = min(width, floor(room))
            let x = side == .right ? wechatFrame.maxX + dockGap : wechatFrame.minX - dockGap - fitWidth
            let frame = NSRect(x: x, y: y, width: fitWidth, height: height)
            guard visible.contains(frame), !frame.intersects(wechatFrame) else { continue }
            return WeChatDockPlan(side: side, sidebarFrame: frame, tiledWeChatQuartzFrame: nil)
        }
        // No overlay fallback and no implicit movement of the user's WeChat window.
        let frame = NSRect(x: visible.maxX - width, y: y, width: width, height: height)
        return WeChatDockPlan(side: .standalone, sidebarFrame: frame, tiledWeChatQuartzFrame: nil)
    }

    static func constrainedFrame(_ frame: NSRect) -> NSRect {
        guard let visible = screenContaining(frame)?.visibleFrame else { return frame }
        let size = NSSize(width: min(frame.width, visible.width), height: min(frame.height, visible.height))
        return NSRect(x: min(max(frame.minX, visible.minX), visible.maxX - size.width),
                      y: min(max(frame.minY, visible.minY), visible.maxY - size.height),
                      width: size.width, height: size.height)
    }
}

private func wechatAXDockCallback(
    observer _: AXObserver,
    element _: AXUIElement,
    notification: CFString,
    refcon: UnsafeMutableRawPointer?
) {
    guard let refcon else { return }
    let controller = Unmanaged<StudioAppDelegate>.fromOpaque(refcon).takeUnretainedValue()
    let name = notification as String
    DispatchQueue.main.async {
        controller.handleWeChatAXEvent(name)
    }
}

final class StudioAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private let repoRoot: URL
    private let consoleUrl: String
    private let initialDockWeChat: Bool
    private let initialTileWeChat: Bool

    private var window: NSWindow!
    private var webView: WKWebView!
    private var statusLabel: NSTextField!
    private var btnDockToggle: NSButton!
    private var btnTileSplit: NSButton!
    private var btnCollapse: NSButton!
    private var secondaryButtons: [NSButton] = []

    private var isDockedToWeChat = false
    private var isCollapsed = false
    private var preferredSide: WeChatDockSide? = nil
    private var lastDockSide: WeChatDockSide? = nil
    private var sidebarWidth: CGFloat = WeChatDockGeometry.defaultSidebarWidth
    private var undockedFrame: NSRect?
    private var dockedWindowID: CGWindowID?
    private var dockedOwnerPID: pid_t?
    private var dockTimer: Timer?
    private var isApplyingFrame = false
    private var axObserver: AXObserver?
    private var axTargetWindow: AXUIElement?
    private var collapsedBanner: NSView?
    private var statusItem: NSStatusItem?
    private var lifecycleMenuItem: NSMenuItem?
    private var serviceMenuItem: NSMenuItem?
    private var serviceTimer: Timer?
    private var userBackgrounded = false
    private var hiddenForTarget = false
    private var dockingPaused = false
    private var hasDockedFrame = false
    private var explicitStandalone = false
    private var dockStatus = "独立窗口"

    private let regularStyleMask: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]

    init(repoRoot: URL, consoleUrl: String, dockWeChat: Bool = false, tileWeChat: Bool = false) {
        self.repoRoot = repoRoot
        self.consoleUrl = consoleUrl
        self.initialDockWeChat = dockWeChat
        self.initialTileWeChat = tileWeChat
        super.init()
    }

    // MARK: - 启动权限预检（影刀式：App 一启动就检查，缺权限直接弹原生引导窗）

    /// 原生权限预检：辅助功能（AX）+ 屏幕录制。子进程（wechat-vision-ax）由本 App 启动，
    /// TCC 归属本 App bundle，因此检查本进程即可代表整条链路。
    private func preflightPermissionsIfNeeded() {
        let axGranted = AXIsProcessTrusted()
        let screenGranted = CGPreflightScreenCaptureAccess()
        guard !axGranted || !screenGranted else { return }  // 全绿：不打扰

        // 窗口先出，再弹引导（延迟到主队列下一拍，避免与首帧竞态）
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
            guard self?.window != nil else { return }
            let missing = [
                axGranted ? nil : "辅助功能",
                screenGranted ? nil : "屏幕录制",
            ].compactMap { $0 }.joined(separator: "、")
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "需要授权以下权限才能正常使用 WeChat Bot"
            alert.informativeText = """
                缺少权限：\(missing)

                ① 点「打开系统设置」→ 隐私与安全性
                ② 在「辅助功能」和「屏幕录制」两个面板里，把 WeChat Bot 加进去并打开开关
                ③ 若列表里有旧条目，先「−」删除再重新添加（旧授权对新版本无效）
                ④ 授权后回到本应用，控制台首页点「🔄 重新检查」即可生效
                """
            alert.addButton(withTitle: "⚙️ 打开系统设置")
            alert.addButton(withTitle: "稍后再说")
            let resp = alert.runModal()
            if resp == .alertFirstButtonReturn {
                let pane = axGranted
                    ? "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
                    : "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
                if let url = URL(string: pane) {
                    NSWorkspace.shared.open(url)
                }
            }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        ensureBackendRunning(repoRoot: repoRoot, consoleUrl: consoleUrl)
        preflightPermissionsIfNeeded()

        let frame = NSRect(x: 0, y: 0, width: 1380, height: 880)
        window = NSWindow(
            contentRect: frame,
            styleMask: regularStyleMask,
            backing: .buffered,
            defer: false
        )
        window.title = "WeChat Bot"
        window.backgroundColor = NSColor.windowBackgroundColor
        window.minSize = NSSize(width: WeChatDockGeometry.collapsedSidebarWidth, height: 360)
        window.delegate = self
        window.isReleasedWhenClosed = false
        installReturnMenu()
        window.center()
        window.setFrame(WeChatDockGeometry.constrainedFrame(window.frame), display: false)

        let rootView = NSView(frame: frame)
        rootView.autoresizingMask = [.width, .height]

        let barHeight: CGFloat = 36
        let toolbar = NSView(frame: NSRect(x: 0, y: frame.height - barHeight, width: frame.width, height: barHeight))
        toolbar.wantsLayer = true
        toolbar.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        toolbar.autoresizingMask = [.width, .minYMargin]
        let divider = NSView(frame: NSRect(x: 0, y: 0, width: frame.width, height: 1))
        divider.wantsLayer = true
        divider.layer?.backgroundColor = NSColor.separatorColor.cgColor
        divider.autoresizingMask = [.width, .maxYMargin]
        toolbar.addSubview(divider)

        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false

        btnDockToggle = NSButton(title: "贴靠微信", target: self, action: #selector(onToggleDock))
        btnCollapse = NSButton(title: "收起", target: self, action: #selector(onToggleCollapse))
        btnCollapse.isHidden = true
        let btnWatch = NSButton(title: "立即巡检", target: self, action: #selector(onWatchOnce))
        let btnSettings = NSButton(title: "⚙️ 设置", target: self, action: #selector(onOpenSettings))

        btnTileSplit = NSButton(title: "并排", target: self, action: #selector(onTileWithWeChat))
        let btnRefresh = NSButton(title: "刷新", target: self, action: #selector(onRefresh))
        let btnBrowser = NSButton(title: "浏览器", target: self, action: #selector(onOpenBrowser))
        secondaryButtons = [btnTileSplit!, btnRefresh, btnBrowser]

        for b in [btnDockToggle!, btnCollapse!, btnWatch, btnSettings] {
            b.bezelStyle = .rounded
            b.font = NSFont.systemFont(ofSize: 11.5, weight: .medium)
            b.setContentCompressionResistancePriority(.defaultHigh, for: .horizontal)
            stack.addArrangedSubview(b)
        }

        stack.addArrangedSubview(NSView())

        for b in secondaryButtons {
            b.bezelStyle = .recessed
            b.isBordered = true
            b.font = NSFont.systemFont(ofSize: 11.5, weight: .regular)
            b.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
            b.isHidden = true
            stack.addArrangedSubview(b)
        }

        statusLabel = NSTextField(labelWithString: "在线 · 随时可接管")
        statusLabel.font = NSFont.systemFont(ofSize: 11.5, weight: .regular)
        statusLabel.textColor = NSColor.secondaryLabelColor
        statusLabel.lineBreakMode = .byTruncatingTail
        stack.addArrangedSubview(statusLabel)

        toolbar.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: toolbar.leadingAnchor, constant: 8),
            stack.trailingAnchor.constraint(equalTo: toolbar.trailingAnchor, constant: -8),
            stack.topAnchor.constraint(equalTo: toolbar.topAnchor),
            stack.bottomAnchor.constraint(equalTo: toolbar.bottomAnchor),
        ])

        let webConfig = WKWebViewConfiguration()
        webView = WKWebView(
            frame: NSRect(x: 0, y: 0, width: frame.width, height: frame.height - barHeight),
            configuration: webConfig
        )
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self

        // Slim collapsed sidebar pill overlay shown only when collapsed
        let banner = NSView(frame: NSRect(x: 0, y: 0, width: frame.width, height: frame.height - barHeight))
        banner.autoresizingMask = [.width, .height]
        banner.wantsLayer = true
        banner.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        banner.isHidden = true
        let expandBtn = NSButton(title: "▶\n展\n开\n侧\n栏", target: self, action: #selector(onToggleCollapse))
        expandBtn.bezelStyle = .rounded
        expandBtn.translatesAutoresizingMaskIntoConstraints = false
        banner.addSubview(expandBtn)
        NSLayoutConstraint.activate([
            expandBtn.centerXAnchor.constraint(equalTo: banner.centerXAnchor),
            expandBtn.centerYAnchor.constraint(equalTo: banner.centerYAnchor),
            expandBtn.widthAnchor.constraint(equalToConstant: 42),
            expandBtn.heightAnchor.constraint(equalToConstant: 140),
        ])
        self.collapsedBanner = banner

        rootView.addSubview(webView)
        rootView.addSubview(banner)
        rootView.addSubview(toolbar)
        window.contentView = rootView
        if !initialDockWeChat && !initialTileWeChat {
            updateToolbarCompactState(compact: false)
        }
        if !initialDockWeChat || initialTileWeChat {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }

        if let url = URL(string: consoleUrl) {
            webView.load(URLRequest(url: url))
        }

        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.openbot.wechatstudio.dockCommand"),
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let self else { return }
            let mode = (note.object as? String ?? "dock").lowercased()
            if mode == "tile" {
                self.onTileWithWeChat()
            } else if mode == "undock" {
                self.disableWeChatDock(restoreFrame: true)
            } else {
                self.enableWeChatDock(animate: true)
            }
        }

        if initialTileWeChat {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                self?.onTileWithWeChat()
            }
        } else if initialDockWeChat {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                self?.enableWeChatDock(animate: false)
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func windowWillClose(_ notification: Notification) {
        // A real NSWindow close (also Cmd+W), while retaining the window for Dock reopen.
        userBackgrounded = true
        updateLifecycleStatus()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showStudio()
        return false
    }

    func applicationWillUnhide(_ notification: Notification) {
        DispatchQueue.main.async { [weak self] in self?.updateDockedFrame(animate: false) }
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopDockTimer()
        stopAXObserver()
        serviceTimer?.invalidate()
        if let statusItem { NSStatusBar.system.removeStatusItem(statusItem) }
    }

    private func installReturnMenu() {
        let appMenu = NSMenu()
        let root = NSMenuItem()
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "退出 WeChat Bot", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        root.submenu = applicationMenu
        appMenu.addItem(root)
        let editRoot = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("剪切", "cut:", "x"), ("复制", "copy:", "c"),
                                     ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editRoot.submenu = editMenu
        appMenu.addItem(editRoot)
        let windowRoot = NSMenuItem()
        let windowMenu = NSMenu(title: "窗口")
        let close = windowMenu.addItem(withTitle: "退到后台", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        close.target = window
        windowRoot.submenu = windowMenu
        appMenu.addItem(windowRoot)
        NSApp.mainMenu = appMenu
        NSApp.windowsMenu = windowMenu

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "WB"
        item.button?.toolTip = "WeChat Bot · 点击返回或查看后台状态"
        let menu = NSMenu()
        lifecycleMenuItem = menu.addItem(withTitle: "窗口已打开", action: nil, keyEquivalent: "")
        serviceMenuItem = menu.addItem(withTitle: "服务状态检查中", action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        for (title, action) in [("打开 WeChat Bot", #selector(showStudio)), ("退到后台", #selector(enterBackground))] {
            let entry = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            entry.target = self
        }
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 WeChat Bot", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.menu = menu
        statusItem = item
        refreshServiceStatus()
        serviceTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.refreshServiceStatus()
        }
    }

    private func refreshServiceStatus() {
        guard let url = URL(string: "\(consoleUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/api/background-observation") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            let payload = data.flatMap { (try? JSONSerialization.jsonObject(with: $0)) as? [String: Any] }
            let statusCode = (response as? HTTPURLResponse)?.statusCode
            let label: String
            if statusCode == 200, (payload?["ok"] as? Bool) == true {
                switch payload?["state"] as? String {
                case "running": label = "后台巡检：运行中"
                case "starting": label = "后台巡检：启动中"
                case "waiting_no_visible_window": label = "后台巡检：等待微信窗口"
                case "failed": label = "后台巡检：读取异常"
                case "stopping": label = "后台巡检：停止中"
                default: label = "后台巡检：未开启"
                }
            } else if statusCode == 403 {
                label = "后台巡检：需要本地授权"
            } else {
                label = "后台巡检：状态不可用"
            }
            DispatchQueue.main.async {
                self?.serviceMenuItem?.title = label
            }
        }.resume()
    }

    private func updateLifecycleStatus() {
        lifecycleMenuItem?.title = userBackgrounded ? "后台运行 · 窗口已关闭" : dockStatus
        statusItem?.button?.toolTip = "WeChat Bot · \(lifecycleMenuItem?.title ?? dockStatus)"
    }

    @objc private func enterBackground() {
        userBackgrounded = true
        window.close()
        updateLifecycleStatus()
    }

    @objc private func showStudio() {
        userBackgrounded = false
        explicitStandalone = true
        hiddenForTarget = false
        if isDockedToWeChat { updateDockedFrame(animate: false) }
        if !window.isVisible && (!isDockedToWeChat || dockingPaused) {
            applyDockFrame(WeChatDockGeometry.constrainedFrame(undockedFrame ?? window.frame), animate: false)
        }
        if window.isMiniaturized {
            window.deminiaturize(nil)
            if isDockedToWeChat { updateDockedFrame(animate: false) }
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        updateLifecycleStatus()
        refreshServiceStatus()
    }

    // MARK: - Sidebar Dock Mechanics (HarvisBar-style)

    @objc private func onToggleDock() {
        if isDockedToWeChat {
            disableWeChatDock(restoreFrame: true)
        } else {
            enableWeChatDock(animate: true)
        }
    }

    @objc private func onToggleCollapse() {
        guard isDockedToWeChat else { return }
        isCollapsed.toggle()
        btnCollapse.title = isCollapsed ? "展开" : "收起"
        updateToolbarCompactState(compact: true)
        webView.isHidden = isCollapsed
        collapsedBanner?.isHidden = !isCollapsed
        for b in secondaryButtons { b.isHidden = true }
        updateDockedFrame(animate: true)
    }

    @objc private func onTileWithWeChat() {
        guard let target = WeChatDockGeometry.findWeChatMainWindow() else {
            statusLabel.stringValue = "未检测到可见微信主窗口，请先唤醒微信"
            return
        }
        let scr = WeChatDockGeometry.screenContaining(target.appKitFrame)
        let visible = scr?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1920, height: 1050)
        let desiredW = min(720, max(WeChatDockGeometry.minimumSidebarWidth, sidebarWidth))
        let available = visible.width - desiredW - WeChatDockGeometry.dockGap
        guard available >= 840 else {
            statusLabel.stringValue = "显示区不足以并排，请保持独立窗口或手动调整微信"
            return
        }
        guard AXIsProcessTrusted(), let targetAX = matchingAXWindow(ownerPID: target.ownerPID, frame: target.appKitFrame) else {
            statusLabel.stringValue = "并排需要已有的辅助功能授权及可识别主窗；请手动调整微信"
            return
        }
        let newH = min(target.appKitFrame.height, visible.height)
        let newAk = NSRect(x: visible.minX,
                           y: min(max(target.appKitFrame.minY, visible.minY), visible.maxY - newH),
                           width: min(target.appKitFrame.width, available), height: newH)
        let newQ = WeChatDockGeometry.quartzFrame(appKitFrame: newAk, mainDisplayTop: WeChatDockGeometry.mainDisplayTop)
        var position = newQ.origin
        var size = newQ.size
        guard let positionValue = AXValueCreate(.cgPoint, &position), let sizeValue = AXValueCreate(.cgSize, &size) else { return }
        let resized = AXUIElementSetAttributeValue(targetAX, kAXSizeAttribute as CFString, sizeValue)
        let moved = AXUIElementSetAttributeValue(targetAX, kAXPositionAttribute as CFString, positionValue)
        guard resized == .success, moved == .success else {
            statusLabel.stringValue = "微信未完成并排调整，请检查窗口位置后重试"
            return
        }
        preferredSide = .right
        isCollapsed = false
        webView.isHidden = false
        collapsedBanner?.isHidden = true
        enableWeChatDock(animate: false, target: target)
    }

    private func enableWeChatDock(animate: Bool, target selectedTarget: WeChatTargetWindow? = nil) {
        guard let target = selectedTarget ?? WeChatDockGeometry.findWeChatMainWindow() else {
            statusLabel.stringValue = "未找到可见微信窗口，保持独立窗口"
            if !userBackgrounded && !window.isVisible { window.orderBack(nil) }
            return
        }
        if !isDockedToWeChat { undockedFrame = window.frame }
        isDockedToWeChat = true
        dockedWindowID = target.windowID
        dockedOwnerPID = target.ownerPID
        btnDockToggle.title = "取消贴靠"
        btnCollapse.isHidden = false
        startAXObserver(ownerPID: target.ownerPID, matching: target.appKitFrame)
        startDockTimer()
        updateDockedFrame(animate: animate)
    }

    private func disableWeChatDock(restoreFrame: Bool) {
        isDockedToWeChat = false
        hiddenForTarget = false
        dockingPaused = false
        hasDockedFrame = false
        lastDockSide = nil
        explicitStandalone = false
        isCollapsed = false
        webView.isHidden = false
        collapsedBanner?.isHidden = true
        dockedWindowID = nil
        dockedOwnerPID = nil
        btnDockToggle.title = "贴靠微信"
        btnCollapse.title = "收起"
        btnCollapse.isHidden = true
        stopDockTimer()
        stopAXObserver()
        applyDockedChrome(false)
        window.level = .normal
        updateToolbarCompactState(compact: false)
        dockStatus = "独立窗口 · 关闭窗口可退到后台"
        statusLabel.stringValue = dockStatus
        updateLifecycleStatus()
        if !userBackgrounded && !window.isMiniaturized { window.orderFront(nil) }
        if restoreFrame, let prev = undockedFrame {
            applyDockFrame(WeChatDockGeometry.constrainedFrame(prev), animate: true)
        }
        undockedFrame = nil
    }

    private func applyDockedChrome(_ docked: Bool) {
        let visible = WeChatDockGeometry.screenContaining(window.frame)?.visibleFrame.size
            ?? NSSize(width: 1920, height: 1050)
        if docked {
            window.titleVisibility = .hidden
            window.collectionBehavior = [.managed]
            window.minSize = NSSize(width: min(WeChatDockGeometry.collapsedSidebarWidth, visible.width), height: min(360, visible.height))
        } else {
            window.titleVisibility = .visible
            window.collectionBehavior = [.managed]
            window.minSize = NSSize(width: min(480, visible.width), height: min(420, visible.height))
        }
    }

    private func applyWindowLevel(side: WeChatDockSide) {
        // Always remain at normal level, including the collapsed strip.
        window.level = .normal
    }

    private func updateToolbarCompactState(compact: Bool) {
        let wideUndocked = !compact && !isDockedToWeChat && (window?.frame.width ?? 0) >= 980
        for b in secondaryButtons {
            b.isHidden = !wideUndocked
        }
        statusLabel.toolTip = statusLabel.stringValue
        statusLabel.isHidden = compact && isCollapsed
    }

    private func applyDockFrame(_ targetFrame: NSRect, animate: Bool) {
        isApplyingFrame = true
        window.setFrame(targetFrame, display: true, animate: animate)
        if animate {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
                self?.isApplyingFrame = false
            }
        } else {
            isApplyingFrame = false
        }
    }

    private func updateDockedFrame(animate: Bool) {
        guard isDockedToWeChat, !isApplyingFrame, !userBackgrounded, !window.isMiniaturized, !NSApp.isHidden else { return }
        guard let windowID = dockedWindowID, let ownerPID = dockedOwnerPID,
              let target = WeChatDockGeometry.findWeChatMainWindow(windowID: windowID, ownerPID: ownerPID) else {
            dockStatus = "贴靠暂停 · 原微信窗口不可见（最小化、关闭或其他空间）"
            statusLabel.stringValue = dockStatus
            if !explicitStandalone {
                hiddenForTarget = true
                window.orderOut(nil)
            } else {
                applyDockedChrome(false)
                if !dockingPaused, let frame = undockedFrame {
                    applyDockFrame(WeChatDockGeometry.constrainedFrame(frame), animate: false)
                }
                dockingPaused = true
            }
            updateLifecycleStatus()
            return
        }
        let plan = WeChatDockGeometry.computeDockPlan(
            wechatFrame: target.appKitFrame, desiredWidth: sidebarWidth,
            collapsed: isCollapsed, preferredSide: preferredSide ?? lastDockSide)
        if plan.side == .standalone {
            if !dockingPaused {
                applyDockedChrome(false)
                if hasDockedFrame && !explicitStandalone {
                    hiddenForTarget = true
                    window.orderOut(nil)
                } else if let frame = undockedFrame {
                    applyDockFrame(WeChatDockGeometry.constrainedFrame(frame), animate: false)
                }
            }
            dockingPaused = true
            dockStatus = "贴靠暂停 · 侧边空间不足，可手动调整或点击并排"
            statusLabel.stringValue = dockStatus
            updateToolbarCompactState(compact: false)
            if !hasDockedFrame && !userBackgrounded && !window.isVisible { window.orderBack(nil) }
            updateLifecycleStatus()
            return
        }
        explicitStandalone = false
        // Space changes must never bring this app in front of an unrelated app.
        if hiddenForTarget && !NSApp.isActive && NSWorkspace.shared.frontmostApplication?.processIdentifier != ownerPID {
            return
        }
        dockingPaused = false
        hasDockedFrame = true
        lastDockSide = plan.side
        applyDockedChrome(true)
        updateToolbarCompactState(compact: true)
        applyWindowLevel(side: plan.side)
        let f = plan.sidebarFrame
        let cur = window.frame
        if abs(cur.minX - f.minX) > 1.5 || abs(cur.minY - f.minY) > 1.5
            || abs(cur.width - f.width) > 1.5 || abs(cur.height - f.height) > 1.5 {
            applyDockFrame(f, animate: animate)
        }
        if hiddenForTarget || !window.isVisible {
            window.order(.below, relativeTo: Int(target.windowID))
            hiddenForTarget = false
        }
        dockStatus = "已贴靠 · \(plan.side == .left ? "左侧" : "右侧")"
        statusLabel.stringValue = dockStatus
        statusLabel.toolTip = "关闭窗口可退到后台"
        updateLifecycleStatus()
    }

    private func startDockTimer() {
        dockTimer?.invalidate()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.22, repeats: true) { [weak self] _ in
            guard let self, NSEvent.pressedMouseButtons & 1 == 0 else { return }
            self.updateDockedFrame(animate: false)
        }
        RunLoop.main.add(timer, forMode: .common)
        dockTimer = timer
    }

    private func stopDockTimer() {
        dockTimer?.invalidate()
        dockTimer = nil
    }

    private func matchingAXWindow(ownerPID: pid_t, frame: NSRect) -> AXUIElement? {
        let appAX = AXUIElementCreateApplication(ownerPID)
        AXUIElementSetMessagingTimeout(appAX, 0.25)
        var raw: CFTypeRef?
        guard AXUIElementCopyAttributeValue(appAX, kAXWindowsAttribute as CFString, &raw) == .success,
              let windows = raw as? [AXUIElement] else { return nil }
        let expected = WeChatDockGeometry.quartzFrame(appKitFrame: frame, mainDisplayTop: WeChatDockGeometry.mainDisplayTop)
        let matches = windows.filter { candidate in
            var positionRaw: CFTypeRef?
            var sizeRaw: CFTypeRef?
            guard AXUIElementCopyAttributeValue(candidate, kAXPositionAttribute as CFString, &positionRaw) == .success,
                  AXUIElementCopyAttributeValue(candidate, kAXSizeAttribute as CFString, &sizeRaw) == .success,
                  let positionRaw, let sizeRaw,
                  CFGetTypeID(positionRaw) == AXValueGetTypeID(), CFGetTypeID(sizeRaw) == AXValueGetTypeID() else { return false }
            var position = CGPoint.zero
            var size = CGSize.zero
            guard AXValueGetValue(unsafeBitCast(positionRaw, to: AXValue.self), .cgPoint, &position),
                  AXValueGetValue(unsafeBitCast(sizeRaw, to: AXValue.self), .cgSize, &size) else { return false }
            return abs(position.x - expected.minX) < 3 && abs(position.y - expected.minY) < 3
                && abs(size.width - expected.width) < 3 && abs(size.height - expected.height) < 3
        }
        return matches.count == 1 ? matches.first : nil
    }

    private func startAXObserver(ownerPID: pid_t, matching frame: NSRect) {
        stopAXObserver()
        guard AXIsProcessTrusted() else { return }
        guard let winEl = matchingAXWindow(ownerPID: ownerPID, frame: frame) else { return }
        var observer: AXObserver?
        guard AXObserverCreate(ownerPID, wechatAXDockCallback, &observer) == .success,
              let obs = observer else {
            return
        }
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        for note in [kAXMovedNotification, kAXResizedNotification, kAXUIElementDestroyedNotification, kAXWindowMiniaturizedNotification, kAXWindowDeminiaturizedNotification] {
            _ = AXObserverAddNotification(obs, winEl, note as CFString, refcon)
        }
        CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(obs), .commonModes)
        axObserver = obs
        axTargetWindow = winEl
    }

    private func stopAXObserver() {
        guard let obs = axObserver else {
            axTargetWindow = nil
            return
        }
        if let winEl = axTargetWindow {
            for note in [kAXMovedNotification, kAXResizedNotification, kAXUIElementDestroyedNotification, kAXWindowMiniaturizedNotification, kAXWindowDeminiaturizedNotification] {
                _ = AXObserverRemoveNotification(obs, winEl, note as CFString)
            }
        }
        CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(obs), .commonModes)
        axObserver = nil
        axTargetWindow = nil
    }

    fileprivate func handleWeChatAXEvent(_ notification: String) {
        guard isDockedToWeChat else { return }
        if notification == kAXUIElementDestroyedNotification as String {
            stopAXObserver()
            hiddenForTarget = true
            window.orderOut(nil)
            dockStatus = "贴靠暂停 · 原微信窗口已关闭；可从菜单返回或重新贴靠"
            statusLabel.stringValue = dockStatus
            updateLifecycleStatus()
            return
        }
        updateDockedFrame(animate: false)
    }

    func windowDidResize(_ notification: Notification) {
        guard let window else { return }
        let narrow = isDockedToWeChat || window.frame.width < 980
        updateToolbarCompactState(compact: narrow)
        if isDockedToWeChat && !dockingPaused && !isApplyingFrame && !isCollapsed && window.frame.width >= WeChatDockGeometry.minimumSidebarWidth {
            sidebarWidth = min(720, window.frame.width)
        }
    }

    // MARK: - Actions

    @objc private func onRefresh() {
        webView.reload()
    }

    @objc private func onOpenBrowser() {
        if let url = URL(string: consoleUrl) {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func onWakeWeChat() {
        let axBin = resolveVisionAxBinary(repoRoot: repoRoot)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            if let axBin {
                let p = Process()
                p.executableURL = axBin
                p.arguments = ["activate"]
                p.standardOutput = FileHandle.nullDevice
                p.standardError = FileHandle.nullDevice
                try? p.run()
                p.waitUntilExit()
            }
            DispatchQueue.main.async {
                self?.statusLabel.stringValue = "已发送微信主窗唤醒指令"
                if self?.isDockedToWeChat == true {
                    self?.updateDockedFrame(animate: true)
                }
            }
        }
    }

    @objc private func onOpenWorkbench() {
        if let url = URL(string: "\(consoleUrl)/workbench") {
            webView.load(URLRequest(url: url))
        }
    }

    @objc private func onOpenBotStudioTab() {
        if webView.url?.path == "/workbench", let url = URL(string: "\(consoleUrl)/#open") {
            webView.load(URLRequest(url: url))
            return
        }
        webView.evaluateJavaScript("if (typeof switchTab === 'function') { switchTab('open'); }", completionHandler: nil)
    }

    @objc private func onWatchOnce() {
        webView.evaluateJavaScript("if (typeof triggerWatchOnce === 'function') { triggerWatchOnce(false); }", completionHandler: nil)
    }

    @objc private func onOpenSettings() {
        webView.evaluateJavaScript("if (typeof openSettingsModal === 'function') { openSettingsModal(); }", completionHandler: nil)
    }
}

private func renderAppIconPng(size: Int, to url: URL) throws {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: size,
        pixelsHigh: size,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { return }
    rep.size = NSSize(width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    let s = CGFloat(size)
    let inset = s * 0.06
    let bgRect = NSRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
    let bgPath = NSBezierPath(roundedRect: bgRect, xRadius: s * 0.22, yRadius: s * 0.22)
    let grad = NSGradient(
        starting: NSColor(calibratedRed: 0.04, green: 0.78, blue: 0.39, alpha: 1.0),
        ending: NSColor(calibratedRed: 0.02, green: 0.62, blue: 0.31, alpha: 1.0)
    )
    grad?.draw(in: bgPath, angle: -90)

    let b1 = NSBezierPath(ovalIn: NSRect(x: s * 0.18, y: s * 0.37, width: s * 0.48, height: s * 0.38))
    NSColor.white.withAlphaComponent(0.95).setFill()
    b1.fill()

    let b2 = NSBezierPath(ovalIn: NSRect(x: s * 0.41, y: s * 0.25, width: s * 0.41, height: s * 0.32))
    NSColor(calibratedRed: 0.90, green: 1.0, blue: 0.93, alpha: 1.0).setFill()
    b2.fill()

    let eyeColor = NSColor(calibratedRed: 0.03, green: 0.50, blue: 0.25, alpha: 1.0)
    eyeColor.setFill()
    let eyeR = max(1.5, s * 0.032)
    NSBezierPath(ovalIn: NSRect(x: s * 0.32 - eyeR, y: s * 0.59 - eyeR, width: eyeR * 2, height: eyeR * 2)).fill()
    NSBezierPath(ovalIn: NSRect(x: s * 0.49 - eyeR, y: s * 0.59 - eyeR, width: eyeR * 2, height: eyeR * 2)).fill()

    let badgeRect = NSRect(x: s * 0.61, y: s * 0.17, width: s * 0.23, height: s * 0.23)
    NSColor(calibratedRed: 0.07, green: 0.13, blue: 0.18, alpha: 0.92).setFill()
    NSBezierPath(ovalIn: badgeRect).fill()
    let innerDot = NSRect(x: s * 0.675, y: s * 0.235, width: s * 0.10, height: s * 0.10)
    NSColor(calibratedRed: 0.22, green: 0.96, blue: 0.56, alpha: 1.0).setFill()
    NSBezierPath(ovalIn: innerDot).fill()

    NSGraphicsContext.restoreGraphicsState()
    if let pngData = rep.representation(using: .png, properties: [:]) {
        try pngData.write(to: url)
    }
}

private func generateIconset(at dirPath: String) -> Bool {
    let dirUrl = URL(fileURLWithPath: dirPath)
    do {
        try FileManager.default.createDirectory(at: dirUrl, withIntermediateDirectories: true)
        let specs: [(String, Int)] = [
            ("icon_16x16.png", 16),
            ("icon_16x16@2x.png", 32),
            ("icon_32x32.png", 32),
            ("icon_32x32@2x.png", 64),
            ("icon_128x128.png", 128),
            ("icon_128x128@2x.png", 256),
            ("icon_256x256.png", 256),
            ("icon_256x256@2x.png", 512),
            ("icon_512x512.png", 512),
            ("icon_512x512@2x.png", 1024),
        ]
        for (name, px) in specs {
            try renderAppIconPng(size: px, to: dirUrl.appendingPathComponent(name))
        }
        return true
    } catch {
        return false
    }
}

private func mainEntry() {
    let args = CommandLine.arguments
    let repoRoot = resolveRepoRoot()
    var consoleUrl = ProcessInfo.processInfo.environment["WECHAT_CONSOLE_URL"] ?? "http://127.0.0.1:18788/"
    if let idx = args.firstIndex(of: "--url"), idx + 1 < args.count {
        consoleUrl = args[idx + 1]
    }

    if let idx = args.firstIndex(of: "--generate-iconset"), idx + 1 < args.count {
        let ok = generateIconset(at: args[idx + 1])
        print(ok ? "{\"ok\":true}" : "{\"ok\":false}")
        exit(ok ? 0 : 1)
    }

    if let nIdx = args.firstIndex(of: "--notify-dock") {
        let mode = (nIdx + 1 < args.count) ? args[nIdx + 1] : "dock"
        DistributedNotificationCenter.default().postNotificationName(
            Notification.Name("com.openbot.wechatstudio.dockCommand"),
            object: mode,
            userInfo: nil,
            deliverImmediately: true
        )
        print("{\"ok\":true,\"notifiedDock\":true,\"mode\":\"\(mode)\"}")
        return
    }

    if args.contains("--verify-dock-geometry") {
        let visible = NSRect(x: 0, y: 24, width: 1600, height: 1000)
        let cases: [(String, NSRect, NSRect, CGFloat, Bool, WeChatDockSide?, WeChatDockSide)] = [
            ("right_gap", NSRect(x: 0, y: 100, width: 1000, height: 800), visible, 430, false, nil, .right),
            ("left_gap", NSRect(x: 600, y: 100, width: 1000, height: 800), visible, 430, false, nil, .left),
            ("full_width_pauses", NSRect(x: 0, y: 24, width: 1600, height: 1000), visible, 430, false, nil, .standalone),
            ("insufficient_gap", NSRect(x: 0, y: 100, width: 1231, height: 800), visible, 430, false, nil, .standalone),
            ("exact_fit", NSRect(x: 0, y: 100, width: 1230, height: 800), visible, 430, false, nil, .right),
            ("collapsed_outside", NSRect(x: 0, y: 100, width: 1500, height: 800), visible, 430, true, nil, .right),
            ("collapsed_full_width_pauses", NSRect(x: 0, y: 24, width: 1600, height: 1000), visible, 430, true, nil, .standalone),
            ("preferred_side_fallback", NSRect(x: 600, y: 100, width: 1000, height: 800), visible, 430, false, .right, .left),
            ("negative_display", NSRect(x: -1600, y: -100, width: 900, height: 800), NSRect(x: -1600, y: -176, width: 1600, height: 1000), 720, false, nil, .right),
            ("short_display", NSRect(x: 0, y: -200, width: 700, height: 900), NSRect(x: 0, y: 24, width: 1100, height: 600), 430, false, nil, .right),
            ("narrow_display", NSRect(x: 0, y: 24, width: 300, height: 500), NSRect(x: 0, y: 24, width: 320, height: 600), 720, false, nil, .standalone),
        ]
        let results: [[String: Any]] = cases.map { name, target, screen, width, collapsed, preferred, expected in
            let plan = WeChatDockGeometry.computeDockPlan(wechatFrame: target, desiredWidth: width,
                collapsed: collapsed, preferredSide: preferred, visibleFrame: screen)
            let frame = plan.sidebarFrame
            let gap = plan.side == .right ? frame.minX - target.maxX : target.minX - frame.maxX
            let safe = plan.side == .standalone || (!frame.intersects(target) && gap >= WeChatDockGeometry.dockGap)
            return ["name": name, "passed": plan.side == expected && screen.contains(frame) && safe,
                    "side": plan.side.rawValue, "noAutomaticTile": plan.tiledWeChatQuartzFrame == nil]
        }
        let ok = results.allSatisfy { ($0["passed"] as? Bool) == true && ($0["noAutomaticTile"] as? Bool) == true }
        let payload: [String: Any] = ["ok": ok, "cases": results, "dockGap": WeChatDockGeometry.dockGap]
        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
           let output = String(data: data, encoding: .utf8) { print(output) }
        exit(ok ? 0 : 1)
    }

    if args.contains("--verify-dock") {
        let _ = NSApplication.shared
        let target = WeChatDockGeometry.findWeChatMainWindow()
        var payload: [String: Any] = [
            "ok": true,
            "accessibilityTrusted": AXIsProcessTrusted(),
            "sidebarDefaultWidth": WeChatDockGeometry.defaultSidebarWidth,
            "supportedModes": ["dock_right", "dock_left", "overlay_right", "tile_split", "collapsed", "standalone"],
            "harvisBarPattern": "CodexDockGeometry + CGWindowListCopyWindowInfo + AXObserverCreate(kAXMoved/Resized)",
            "wechatFound": target != nil,
            "automaticOverlayEnabled": false,
            "dockGap": WeChatDockGeometry.dockGap,
            "closeKeepsProcessAlive": true,
            "returnMethods": ["status_menu", "dock_reopen"],
        ]
        if let t = target {
            let plan = WeChatDockGeometry.computeDockPlan(
                wechatFrame: t.appKitFrame,
                desiredWidth: WeChatDockGeometry.defaultSidebarWidth
            )
            payload["wechatWindow"] = [
                "windowID": t.windowID,
                "ownerPID": t.ownerPID,
                "title": t.title,
                "appKitFrame": [
                    "x": t.appKitFrame.minX,
                    "y": t.appKitFrame.minY,
                    "width": t.appKitFrame.width,
                    "height": t.appKitFrame.height,
                ],
                "quartzFrame": [
                    "x": t.quartzFrame.minX,
                    "y": t.quartzFrame.minY,
                    "width": t.quartzFrame.width,
                    "height": t.quartzFrame.height,
                ],
            ] as [String: Any]
            payload["calculatedDockPlan"] = [
                "side": plan.side.rawValue,
                "sidebarFrame": [
                    "x": plan.sidebarFrame.minX,
                    "y": plan.sidebarFrame.minY,
                    "width": plan.sidebarFrame.width,
                    "height": plan.sidebarFrame.height,
                ],
            ] as [String: Any]
            if let tq = plan.tiledWeChatQuartzFrame {
                payload["tiledWeChatTargetQuartzFrame"] = [
                    "x": tq.origin.x,
                    "y": tq.origin.y,
                    "width": tq.width,
                    "height": tq.height,
                ]
            }
        }
        if let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
           let text = String(data: jsonData, encoding: .utf8) {
            print(text)
        } else {
            print("{\"ok\":true}")
        }
        return
    }

    if args.contains("--verify-headless") {
        let bundledAxExists = resolveVisionAxBinary(repoRoot: repoRoot) != nil
        let exeUrl = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let onRemovableVolume = exeUrl.path.hasPrefix("/Volumes/")
        let consoleHealthy = isConsoleHealthy(consoleUrl)
        let backendScriptExists: Bool = {
            if onRemovableVolume || !repoRoot.path.hasPrefix("/Volumes/") {
                return FileManager.default.isExecutableFile(
                    atPath: repoRoot.appendingPathComponent("bin/wechat-bot").path
                )
            }
            // Internal /Users/*/Applications/*.app stays self-contained to avoid removable-volume TCC popups
            return bundledAxExists || consoleHealthy
        }()
        let payload: [String: Any] = [
            "ok": true,
            "appTitle": "WeChat Bot",
            "displayName": "WeChat Bot",
            "bundleId": Bundle.main.bundleIdentifier ?? "com.openbot.wechat-bot",
            "defaultConsoleUrl": consoleUrl,
            "repoRoot": repoRoot.path,
            "supportsWeChatSidebarDock": true,
            "bundledVisionAxExists": bundledAxExists,
            "consoleHealthy": consoleHealthy,
            "backendScriptExists": backendScriptExists,
        ]
        if let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
           let text = String(data: jsonData, encoding: .utf8) {
            print(text)
        } else {
            print("{\"ok\":true}")
        }
        return
    }

    let dockWeChat = args.contains("--dock-wechat") || args.contains("--sidebar")
    let tileWeChat = args.contains("--tile-wechat")

    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    let delegate = StudioAppDelegate(
        repoRoot: repoRoot,
        consoleUrl: consoleUrl,
        dockWeChat: dockWeChat,
        tileWeChat: tileWeChat
    )
    app.delegate = delegate
    app.run()
}

mainEntry()
