import AppKit
import ApplicationServices
import AVFoundation
import CoreAudio
import CoreGraphics
import Foundation
import ImageIO
import PDFKit
import Vision

// MARK: - JSON Helpers

func writeJSON(_ object: [String: Any], exitCode: Int32 = 0) -> Never {
    let options: JSONSerialization.WritingOptions = [.prettyPrinted, .sortedKeys]
    if let data = try? JSONSerialization.data(withJSONObject: object, options: options),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    } else {
        print("{\"ok\":false,\"error\":\"json_serialization_failed\"}")
    }
    exit(exitCode)
}

func failJSON(_ message: String, code: String = "error", extra: [String: Any] = [:], exitCode: Int32 = 1) -> Never {
    var payload: [String: Any] = [
        "ok": false,
        "error_code": code,
        "error": message,
    ]
    for (k, v) in extra {
        payload[k] = v
    }
    writeJSON(payload, exitCode: exitCode)
}

// MARK: - CLI Arg Parser

func parseArgs() -> (command: String, flags: Set<String>, options: [String: String]) {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let cmd = args.first else {
        return ("help", [], [:])
    }
    var flags = Set<String>()
    var options: [String: String] = [:]
    var i = 1
    while i < args.count {
        let arg = args[i]
        if arg.hasPrefix("--") {
            let key = String(arg.dropFirst(2))
            if i + 1 < args.count && !args[i + 1].hasPrefix("--") {
                options[key] = args[i + 1]
                i += 2
            } else {
                flags.insert(key)
                i += 1
            }
        } else {
            i += 1
        }
    }
    return (cmd, flags, options)
}

// MARK: - Accessibility & Dual-App Helpers

let wechatBundleID = "com.tencent.xinWeChat"
let wecomBundleID = "com.tencent.WeWorkMac"
let feishuBundleIDs = ["com.bytedance.macos.feishu", "com.electron.lark"]
let dingtalkBundleIDs = ["com.alibaba.DingTalkMac"]
let xiaohongshuBundleIDs = ["com.xingin.xhs"]
let douyinBundleIDs = ["com.bytedance.douyin.desktop"]

enum AppKind: String, CaseIterable {
    case wechat
    case wecom
    case feishu
    case dingtalk
    case xiaohongshu
    case douyin

    var appId: String { rawValue }
    var appLabel: String {
        switch self {
        case .wechat: return "微信"
        case .wecom: return "企业微信"
        case .feishu: return "飞书"
        case .dingtalk: return "钉钉"
        case .xiaohongshu: return "小红书"
        case .douyin: return "抖音"
        }
    }
    var bundleIDs: [String] {
        switch self {
        case .wechat: return [wechatBundleID]
        case .wecom: return [wecomBundleID]
        case .feishu: return feishuBundleIDs
        case .dingtalk: return dingtalkBundleIDs
        case .xiaohongshu: return xiaohongshuBundleIDs
        case .douyin: return douyinBundleIDs
        }
    }
    var bundleID: String { bundleIDs[0] }
    var isElectronLike: Bool {
        switch self {
        case .feishu, .dingtalk, .douyin: return true
        case .wechat, .wecom, .xiaohongshu: return false
        }
    }
    var mainTitles: [String] {
        switch self {
        case .wechat: return ["微信", "WeChat"]
        case .wecom: return ["企业微信", "WeCom"]
        case .feishu: return ["飞书", "Lark", "Feishu"]
        case .dingtalk: return ["钉钉", "DingTalk"]
        case .xiaohongshu: return ["小红书", "REDnote", "Xiaohongshu"]
        case .douyin: return ["抖音", "Douyin"]
        }
    }
    var notRunningErrorCode: String {
        return "\(rawValue)_not_running"
    }

    static func fromCLI(_ raw: String) -> AppKind? {
        switch raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "wechat": return .wechat
        case "wecom", "wework": return .wecom
        case "feishu", "lark": return .feishu
        case "dingtalk", "ding": return .dingtalk
        case "xiaohongshu", "xhs", "rednote": return .xiaohongshu
        case "douyin", "tiktok": return .douyin
        default: return nil
        }
    }
}

func enableElectronAccessibility(pid: pid_t, kind: AppKind) {
    guard kind.isElectronLike, AXIsProcessTrusted() else { return }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 0.25)
    _ = AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    _ = AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
}

let inputIdentifiers: Set<String> = [
    "chat_input",
    "chat_input_field",
    "input_field",
    "msg_input",
    "edit_input",
]

func axAttr(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
    AXUIElementSetMessagingTimeout(element, 0.15)
    var value: CFTypeRef?
    let err = AXUIElementCopyAttributeValue(element, key as CFString, &value)
    guard err == .success else { return nil }
    return value
}

func axString(_ element: AXUIElement, _ key: String) -> String? {
    guard let raw = axAttr(element, key) else { return nil }
    if let s = raw as? String {
        let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
    return nil
}

func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    return (axAttr(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}

func axPoint(_ element: AXUIElement, _ key: String) -> CGPoint? {
    guard let raw = axAttr(element, key), CFGetTypeID(raw) == AXValueGetTypeID() else { return nil }
    let axVal = unsafeBitCast(raw, to: AXValue.self)
    var pt = CGPoint.zero
    if AXValueGetType(axVal) == .cgPoint && AXValueGetValue(axVal, .cgPoint, &pt) {
        return pt
    }
    return nil
}

func axSize(_ element: AXUIElement, _ key: String) -> CGSize? {
    guard let raw = axAttr(element, key), CFGetTypeID(raw) == AXValueGetTypeID() else { return nil }
    let axVal = unsafeBitCast(raw, to: AXValue.self)
    var sz = CGSize.zero
    if AXValueGetType(axVal) == .cgSize && AXValueGetValue(axVal, .cgSize, &sz) {
        return sz
    }
    return nil
}

func matchesRunningApp(_ app: NSRunningApplication, kind: AppKind) -> Bool {
    guard !app.isTerminated else { return false }
    let bid = app.bundleIdentifier ?? ""
    if kind.bundleIDs.contains(bid) {
        return true
    }
    let bidLower = bid.lowercased()
    let isHelper = bidLower.contains("helper")
        || bidLower.contains("renderer")
        || bidLower.contains(".gpu")
        || bidLower.contains("crashpad")
        || bidLower.contains("wechatappex")
        || bidLower.contains("inputmethod")
        || bidLower.contains("openbot")
        || bidLower.contains("botstudio")
        || bidLower.contains("agentassistant")
        || bidLower.hasPrefix("com.apple.")
    if isHelper {
        return false
    }
    let name = app.localizedName ?? ""
    let nameLower = name.lowercased()
    switch kind {
    case .wechat:
        return name == "WeChat" || name == "微信"
    case .wecom:
        return bidLower != wechatBundleID.lowercased() && (
            bidLower == wecomBundleID.lowercased()
            || name.contains("企业微信")
            || nameLower.contains("wecom")
        )
    case .feishu:
        return name == "飞书" || name == "Feishu" || name == "Lark"
            || name.hasPrefix("飞书 ") || nameLower.hasPrefix("lark ")
    case .dingtalk:
        return name == "钉钉" || name == "DingTalk" || nameLower == "aliwork"
    case .xiaohongshu:
        return name == "小红书" || nameLower == "xiaohongshu" || nameLower == "rednote"
    case .douyin:
        return name == "抖音" || nameLower == "douyin"
    }
}

func findRunningApps(for kind: AppKind) -> [NSRunningApplication] {
    var seenPIDs = Set<pid_t>()
    var result: [NSRunningApplication] = []
    for bid in kind.bundleIDs {
        for app in NSRunningApplication.runningApplications(withBundleIdentifier: bid) {
            guard !app.isTerminated else { continue }
            if seenPIDs.insert(app.processIdentifier).inserted {
                result.append(app)
            }
        }
    }
    if result.isEmpty {
        for app in NSWorkspace.shared.runningApplications where matchesRunningApp(app, kind: kind) {
            if seenPIDs.insert(app.processIdentifier).inserted {
                result.append(app)
            }
        }
    }
    return result
}

func copyOnScreenWindowInfo() -> [[String: Any]] {
    return (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]) ?? []
}

struct WindowCandidate {
    let windowID: CGWindowID
    let appId: String
    let appLabel: String
    let bundleID: String
    let pid: pid_t
    let title: String
    let isMainWindow: Bool
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    var area: Double { width * height }

    func toDict() -> [String: Any] {
        return [
            "windowID": windowID,
            "appId": appId,
            "appLabel": appLabel,
            "bundleID": bundleID,
            "pid": Int(pid),
            "title": title,
            "isMainWindow": isMainWindow,
            "bounds": ["x": x, "y": y, "width": width, "height": height],
        ]
    }
}

private struct AXWindowMeta {
    let element: AXUIElement
    let frame: CGRect
    let title: String
    let subrole: String
}

private func collectAXWindowMeta(pid: pid_t) -> [AXWindowMeta] {
    guard AXIsProcessTrusted() else { return [] }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 0.25)
    guard let windows = axAttr(app, kAXWindowsAttribute) as? [AXUIElement] else { return [] }
    return windows.map { win in
        let pt = axPoint(win, kAXPositionAttribute) ?? .zero
        let sz = axSize(win, kAXSizeAttribute) ?? .zero
        let title = axString(win, kAXTitleAttribute) ?? ""
        let subrole = axString(win, kAXSubroleAttribute) ?? ""
        return AXWindowMeta(element: win, frame: CGRect(origin: pt, size: sz), title: title, subrole: subrole)
    }
}

func listAppWindows(
    for kind: AppKind,
    apps: [NSRunningApplication]? = nil,
    rawWindowList: [[String: Any]]? = nil
) -> [WindowCandidate] {
    let targetApps = apps ?? findRunningApps(for: kind)
    guard !targetApps.isEmpty else { return [] }

    var appByPID: [pid_t: NSRunningApplication] = [:]
    for app in targetApps {
        appByPID[app.processIdentifier] = app
    }

    let rawList = rawWindowList ?? copyOnScreenWindowInfo()
    struct RawWinEntry {
        let wid: CGWindowID
        let pid: pid_t
        let bundleID: String
        let cgTitle: String
        let x: Double
        let y: Double
        let w: Double
        let h: Double
    }

    var seenWindowIDs = Set<CGWindowID>()
    var rawEntries: [RawWinEntry] = []
    for entry in rawList {
        guard let ownerPID = entry[kCGWindowOwnerPID as String] as? pid_t,
              let ownerApp = appByPID[ownerPID],
              (entry[kCGWindowLayer as String] as? Int) == 0,
              let num = entry[kCGWindowNumber as String] as? NSNumber,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              w >= 200, h >= 180 else {
            continue
        }
        let wid = num.uint32Value
        guard seenWindowIDs.insert(wid).inserted else { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let cgTitle = ((entry[kCGWindowName as String] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let bundleID = ownerApp.bundleIdentifier ?? kind.bundleID
        rawEntries.append(RawWinEntry(wid: wid, pid: ownerPID, bundleID: bundleID, cgTitle: cgTitle, x: x, y: y, w: w, h: h))
    }

    guard !rawEntries.isEmpty else { return [] }

    let hasMainNamedTitle = rawEntries.contains { kind.mainTitles.contains($0.cgTitle) }
    let needsAXEnrichment = AXIsProcessTrusted() && (!hasMainNamedTitle || rawEntries.contains { $0.cgTitle.isEmpty })
    var axMetaByPID: [pid_t: [AXWindowMeta]] = [:]
    if needsAXEnrichment {
        for pid in Set(rawEntries.map { $0.pid }) {
            axMetaByPID[pid] = collectAXWindowMeta(pid: pid)
        }
    }

    struct ResolvedEntry {
        let raw: RawWinEntry
        let resolvedTitle: String
        let axSubrole: String
        var area: Double { raw.w * raw.h }
    }

    let resolvedEntries: [ResolvedEntry] = rawEntries.map { item in
        var title = item.cgTitle
        var subrole = ""
        if let metas = axMetaByPID[item.pid] {
            let targetRect = CGRect(x: item.x, y: item.y, width: item.w, height: item.h)
            if let matched = metas.min(by: { lhs, rhs in
                let dl = abs(lhs.frame.origin.x - targetRect.origin.x)
                    + abs(lhs.frame.origin.y - targetRect.origin.y)
                    + abs(lhs.frame.size.width - targetRect.size.width)
                    + abs(lhs.frame.size.height - targetRect.size.height)
                let dr = abs(rhs.frame.origin.x - targetRect.origin.x)
                    + abs(rhs.frame.origin.y - targetRect.origin.y)
                    + abs(rhs.frame.size.width - targetRect.size.width)
                    + abs(rhs.frame.size.height - targetRect.size.height)
                return dl < dr
            }) {
                let delta = abs(matched.frame.origin.x - targetRect.origin.x)
                    + abs(matched.frame.origin.y - targetRect.origin.y)
                    + abs(matched.frame.size.width - targetRect.size.width)
                    + abs(matched.frame.size.height - targetRect.size.height)
                if delta <= 32.0 {
                    subrole = matched.subrole
                    if title.isEmpty && !matched.title.isEmpty {
                        title = matched.title
                    }
                }
            }
        }
        return ResolvedEntry(raw: item, resolvedTitle: title, axSubrole: subrole)
    }

    // Choose at most one main window per app kind.
    var mainIndex: Int? = nil
    var bestMainScore = -1.0
    for (idx, entry) in resolvedEntries.enumerated() {
        var score = -1.0
        if kind.mainTitles.contains(entry.resolvedTitle) {
            score = 100_000_000.0 + entry.area
        } else if kind.mainTitles.contains(where: { !entry.resolvedTitle.isEmpty && entry.resolvedTitle.localizedCaseInsensitiveContains($0) }) && entry.raw.w >= 640 {
            score = 60_000_000.0 + entry.area
        } else if entry.axSubrole == "AXStandardWindow" && entry.raw.w >= 640 && entry.raw.h >= 440 {
            score = 45_000_000.0 + entry.area
        } else if entry.resolvedTitle.isEmpty && (entry.axSubrole == "AXStandardWindow" || entry.raw.w >= 680 || resolvedEntries.count == 1) {
            score = 30_000_000.0 + (entry.axSubrole == "AXStandardWindow" ? 5_000_000.0 : 0.0) + entry.area
        }
        if score > bestMainScore {
            bestMainScore = score
            mainIndex = idx
        }
    }

    var candidates: [WindowCandidate] = []
    for (idx, entry) in resolvedEntries.enumerated() {
        let isMain = (mainIndex == idx)
        let finalTitle = (entry.resolvedTitle.isEmpty && isMain) ? kind.appLabel : entry.resolvedTitle
        candidates.append(WindowCandidate(
            windowID: entry.raw.wid,
            appId: kind.appId,
            appLabel: kind.appLabel,
            bundleID: entry.raw.bundleID,
            pid: entry.raw.pid,
            title: finalTitle,
            isMainWindow: isMain,
            x: entry.raw.x,
            y: entry.raw.y,
            width: entry.raw.w,
            height: entry.raw.h
        ))
    }

    candidates.sort { lhs, rhs in
        if lhs.isMainWindow != rhs.isMainWindow {
            return lhs.isMainWindow && !rhs.isMainWindow
        }
        if lhs.area != rhs.area {
            return lhs.area > rhs.area
        }
        return lhs.windowID < rhs.windowID
    }
    return candidates
}

func listWeChatWindows(pid: pid_t) -> [WindowCandidate] {
    let matchingApps = findRunningApps(for: .wechat).filter { $0.processIdentifier == pid }
    if !matchingApps.isEmpty {
        return listAppWindows(for: .wechat, apps: matchingApps)
    }
    if let app = NSRunningApplication(processIdentifier: pid) {
        return listAppWindows(for: .wechat, apps: [app])
    }
    return []
}

func listWindows(for kind: AppKind, pid: pid_t? = nil) -> [WindowCandidate] {
    if let pid = pid {
        let matching = findRunningApps(for: kind).filter { $0.processIdentifier == pid }
        if !matching.isEmpty {
            return listAppWindows(for: kind, apps: matching)
        }
        if let app = NSRunningApplication(processIdentifier: pid) {
            return listAppWindows(for: kind, apps: [app])
        }
        return []
    }
    return listAppWindows(for: kind)
}

func findBestRunningApp(for kind: AppKind) -> NSRunningApplication? {
    let apps = findRunningApps(for: kind)
    guard apps.count > 1 else { return apps.first }
    let rawList = copyOnScreenWindowInfo()
    let frontPID = NSWorkspace.shared.frontmostApplication?.processIdentifier
    var bestApp: NSRunningApplication?
    var bestScore = -1.0
    for app in apps {
        let wins = listAppWindows(for: kind, apps: [app], rawWindowList: rawList)
        var score = Double(wins.count) * 100_000.0
        if wins.contains(where: { $0.isMainWindow }) {
            score += 1_000_000.0
        }
        score += min(wins.reduce(0.0) { $0 + $1.area }, 5_000_000.0) / 100.0
        if app.processIdentifier == frontPID {
            score += 5_000_000.0
        }
        if wins.isEmpty && AXIsProcessTrusted() {
            let axCount = collectAXWindowMeta(pid: app.processIdentifier).count
            score += Double(axCount) * 500.0
        }
        if score > bestScore {
            bestScore = score
            bestApp = app
        }
    }
    return bestApp ?? apps.first
}

func findWeChatApp() -> NSRunningApplication? {
    return findBestRunningApp(for: .wechat)
}

func isAppFrontmost(_ kind: AppKind) -> (Bool, String) {
    guard let front = NSWorkspace.shared.frontmostApplication else {
        return (false, "none")
    }
    let bid = front.bundleIdentifier ?? ""
    let name = front.localizedName ?? ""
    return (matchesRunningApp(front, kind: kind), "\(name) (\(bid))")
}

func isWeChatFrontmost() -> (Bool, String) {
    return isAppFrontmost(.wechat)
}

func selectTargetWindow(in windows: [WindowCandidate], options: [String: String]) -> WindowCandidate? {
    if let widStr = options["window-id"], let wid = UInt32(widStr) {
        return windows.first { $0.windowID == wid }
    }
    if let titleSub = options["window-title"]?.trimmingCharacters(in: .whitespacesAndNewlines), !titleSub.isEmpty {
        let lowSub = titleSub.lowercased()
        return windows.first { $0.title.lowercased() == lowSub }
            ?? windows.first { $0.title.lowercased().contains(lowSub) }
    }
    return windows.first
}

func resolveAutoApp(options: [String: String] = [:]) -> AppKind {
    let rawList = copyOnScreenWindowInfo()
    let winsByKind: [(AppKind, [WindowCandidate])] = AppKind.allCases.map {
        ($0, listAppWindows(for: $0, rawWindowList: rawList))
    }

    if let widStr = options["window-id"], let wid = UInt32(widStr) {
        for (kind, wins) in winsByKind where wins.contains(where: { $0.windowID == wid }) {
            return kind
        }
    }
    if let titleSub = options["window-title"]?.trimmingCharacters(in: .whitespacesAndNewlines), !titleSub.isEmpty {
        let lowSub = titleSub.lowercased()
        let ordered = winsByKind.sorted { a, b in
            let fa = isAppFrontmost(a.0).0
            let fb = isAppFrontmost(b.0).0
            if fa != fb { return fa && !fb }
            return false
        }
        for (kind, wins) in ordered {
            if wins.contains(where: { $0.title.lowercased() == lowSub || $0.title.lowercased().contains(lowSub) }) {
                return kind
            }
        }
    }
    for (kind, _) in winsByKind where isAppFrontmost(kind).0 {
        return kind
    }
    for (kind, wins) in winsByKind where !wins.isEmpty {
        return kind
    }
    for kind in AppKind.allCases where !findRunningApps(for: kind).isEmpty {
        return kind
    }
    return .wechat
}

func resolveTargetApp(options: [String: String], allowWindowLookupWhenOmitted: Bool = false) -> (requested: String, kind: AppKind) {
    let raw = (options["app"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if raw.isEmpty {
        if allowWindowLookupWhenOmitted, let widStr = options["window-id"], let wid = UInt32(widStr) {
            let rawList = copyOnScreenWindowInfo()
            for kind in AppKind.allCases {
                let wins = listAppWindows(for: kind, rawWindowList: rawList)
                if wins.contains(where: { $0.windowID == wid }) {
                    return ("default", kind)
                }
            }
        }
        return ("default", .wechat)
    }
    if let explicit = AppKind.fromCLI(raw) {
        return (explicit.appId, explicit)
    }
    if raw == "auto" {
        return ("auto", resolveAutoApp(options: options))
    }
    failJSON("Unsupported --app value '\(raw)'. Expected wechat|wecom|feishu|dingtalk|xiaohongshu|douyin|auto.", code: "invalid_argument")
}

func axHasSessionList(_ root: AXUIElement, maxNodes: Int = 120) -> Bool {
    AXUIElementSetMessagingTimeout(root, 0.2)
    let deadline = CFAbsoluteTimeGetCurrent() + 0.25
    var queue = [root]
    var idx = 0
    while idx < queue.count && idx < maxNodes && CFAbsoluteTimeGetCurrent() < deadline {
        let el = queue[idx]
        idx += 1
        let role = axString(el, kAXRoleAttribute) ?? ""
        if role == "AXWebArea" {
            continue
        }
        if let ident = axString(el, kAXIdentifierAttribute) {
            if ident == "session_list" || ident.hasPrefix("session_item_") {
                return true
            }
        }
        queue.append(contentsOf: axChildren(el))
    }
    return false
}

func findMainAXWindow(pid: pid_t, kind: AppKind = .wechat) -> AXUIElement? {
    guard AXIsProcessTrusted() else { return nil }
    enableElectronAccessibility(pid: pid, kind: kind)
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 0.25)
    guard let windows = axAttr(app, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else {
        return nil
    }
    var bestWindow: AXUIElement?
    var bestScore = -1.0
    for win in windows {
        let sz = axSize(win, kAXSizeAttribute) ?? .zero
        if sz.width < 320 || sz.height < 240 { continue }
        var score = sz.width * sz.height
        let title = axString(win, kAXTitleAttribute) ?? ""
        if kind.mainTitles.contains(title) { score += 10_000_000 }
        if kind == .wechat && axHasSessionList(win) { score += 50_000_000 }
        if score > bestScore {
            bestScore = score
            bestWindow = win
        }
    }
    return bestWindow ?? windows.first
}

func findAXWindow(pid: pid_t, kind: AppKind = .wechat, targetWin: WindowCandidate? = nil, reqTitle: String? = nil) -> AXUIElement? {
    guard AXIsProcessTrusted() else { return nil }
    let effectivePID = targetWin?.pid ?? pid
    enableElectronAccessibility(pid: effectivePID, kind: kind)
    let app = AXUIElementCreateApplication(effectivePID)
    AXUIElementSetMessagingTimeout(app, 0.25)
    guard let windows = axAttr(app, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else {
        return nil
    }
    if let tw = targetWin {
        var best: AXUIElement?
        var bestDist = Double.greatestFiniteMagnitude
        for win in windows {
            if let pt = axPoint(win, kAXPositionAttribute), let sz = axSize(win, kAXSizeAttribute) {
                let d = abs(Double(pt.x) - tw.x) + abs(Double(pt.y) - tw.y)
                    + abs(Double(sz.width) - tw.width) + abs(Double(sz.height) - tw.height)
                if d < bestDist {
                    bestDist = d
                    best = win
                }
            }
        }
        if best != nil && bestDist <= 32.0 {
            return best
        }
        let twTitle = tw.title.lowercased()
        if !twTitle.isEmpty {
            if let byTitle = windows.first(where: { (axString($0, kAXTitleAttribute) ?? "").lowercased() == twTitle }) {
                return byTitle
            }
        }
    }
    if let titleSub = reqTitle?.trimmingCharacters(in: .whitespacesAndNewlines), !titleSub.isEmpty {
        let low = titleSub.lowercased()
        if let exact = windows.first(where: { (axString($0, kAXTitleAttribute) ?? "").lowercased() == low }) {
            return exact
        }
        if let partial = windows.first(where: { (axString($0, kAXTitleAttribute) ?? "").lowercased().contains(low) }) {
            return partial
        }
    }
    return findMainAXWindow(pid: effectivePID, kind: kind)
}

func readChatTitleFromAX(pid: pid_t) -> (name: String?, memberCount: Int?) {
    guard AXIsProcessTrusted() else { return (nil, nil) }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 0.2)
    let deadline = CFAbsoluteTimeGetCurrent() + 0.25
    var queue = (axAttr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []
    var idx = 0
    var chatName: String?
    var memberCount: Int?
    while idx < queue.count && idx < 120 && CFAbsoluteTimeGetCurrent() < deadline {
        let el = queue[idx]
        idx += 1
        let role = axString(el, kAXRoleAttribute) ?? ""
        if role == "AXWebArea" {
            continue
        }
        if let ident = axString(el, kAXIdentifierAttribute) {
            if ident == "current_chat_name_label", let val = axString(el, kAXValueAttribute) ?? axString(el, kAXTitleAttribute) {
                chatName = val
            } else if ident == "current_chat_count_label", let val = axString(el, kAXValueAttribute) ?? axString(el, kAXTitleAttribute) {
                let digits = val.filter { $0.isNumber }
                memberCount = Int(digits)
            }
            if chatName != nil && memberCount != nil {
                break
            }
        }
        queue.append(contentsOf: axChildren(el))
    }
    return (chatName, memberCount)
}

func hardwareKeyboardIdleSeconds() -> Double {
    let hidDown = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .keyDown)
    let hidUp = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .keyUp)
    let hidFlags = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .flagsChanged)
    return max(0.0, min(hidDown, hidUp, hidFlags))
}

func queryHIDIdleState() -> [String: Any] {
    let mouseMove = min(
        CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .mouseMoved),
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .mouseMoved)
    )
    let leftDown = min(
        CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .leftMouseDown),
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .leftMouseDown)
    )
    let rightDown = min(
        CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .rightMouseDown),
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .rightMouseDown)
    )
    let scrollWheel = min(
        CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .scrollWheel),
        CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .scrollWheel)
    )
    let hwKeyIdle = hardwareKeyboardIdleSeconds()
    let combinedKeyDown = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown)
    let combinedKeyUp = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyUp)
    let combinedFlags = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .flagsChanged)

    let mouseIdle = min(mouseMove, leftDown, rightDown, scrollWheel)
    let keyboardIdle = min(hwKeyIdle, combinedKeyDown, combinedKeyUp, combinedFlags)
    let anyInputIdle = min(mouseIdle, keyboardIdle)

    let cursorLoc = CGEvent(source: nil)?.location ?? CGPoint(
        x: NSEvent.mouseLocation.x,
        y: CGDisplayBounds(CGMainDisplayID()).height - NSEvent.mouseLocation.y
    )
    return [
        "mouseMoveIdleSeconds": mouseMove,
        "mouseClickIdleSeconds": min(leftDown, rightDown),
        "scrollIdleSeconds": scrollWheel,
        "mouseIdleSeconds": mouseIdle,
        "keyboardIdleSeconds": keyboardIdle,
        "hardwareKeyboardIdleSeconds": hwKeyIdle,
        "keyboardActive": hwKeyIdle < 2.5 || keyboardIdle < 2.5,
        "anyInputIdleSeconds": anyInputIdle,
        "cursorPosition": [
            "x": (cursorLoc.x * 10.0).rounded() / 10.0,
            "y": (cursorLoc.y * 10.0).rounded() / 10.0,
        ],
    ]
}

// MARK: - Vision OCR Helpers

struct OCRElement: Encodable {
    let text: String
    let confidence: Float
    let bbox: BBox
    let center: Point2D
}

struct BBox: Encodable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
}

struct Point2D: Encodable {
    let x: Int
    let y: Int
}

func loadCGImage(at path: String) -> CGImage? {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(src, 0, nil)
}

func saveCGImageAsPNG(_ image: CGImage, to path: String) -> Bool {
    let url = URL(fileURLWithPath: path)
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) else {
        return false
    }
    CGImageDestinationAddImage(dest, image, nil)
    return CGImageDestinationFinalize(dest)
}

func runVisionOCR(cgImage: CGImage, languages: [String] = ["zh-Hans", "en-US"]) throws -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = languages
    request.usesLanguageCorrection = true

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try handler.perform([request])

    let imgW = Double(cgImage.width)
    let imgH = Double(cgImage.height)
    var items: [[String: Any]] = []

    for obs in request.results ?? [] {
        guard let candidate = obs.topCandidates(1).first else { continue }
        let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { continue }
        let box = obs.boundingBox
        // Convert bottom-left normalized coordinates to top-left pixel coordinates
        let x = Int((box.origin.x * imgW).rounded())
        let y = Int(((1.0 - box.origin.y - box.size.height) * imgH).rounded())
        let w = Int((box.size.width * imgW).rounded())
        let h = Int((box.size.height * imgH).rounded())
        let cx = Int(((box.origin.x + box.size.width / 2.0) * imgW).rounded())
        let cy = Int(((1.0 - box.origin.y - box.size.height / 2.0) * imgH).rounded())

        items.append([
            "text": text,
            "confidence": Double(candidate.confidence),
            "bbox": ["x": x, "y": y, "width": w, "height": h],
            "center": ["x": cx, "y": cy],
        ])
    }

    items.sort { lhs, rhs in
        let lc = (lhs["center"] as? [String: Int]) ?? [:]
        let rc = (rhs["center"] as? [String: Int]) ?? [:]
        let ly = lc["y"] ?? 0
        let ry = rc["y"] ?? 0
        if abs(ly - ry) > 10 {
            return ly < ry
        }
        return (lc["x"] ?? 0) < (rc["x"] ?? 0)
    }
    return items
}

func captureWindowImage(_ window: WindowCandidate, nominalResolution: Bool = false) -> CGImage? {
    let options: CGWindowImageOption = nominalResolution
        ? [.boundsIgnoreFraming, .nominalResolution]
        : [.boundsIgnoreFraming, .bestResolution]
    return CGWindowListCreateImage(
        .null,
        .optionIncludingWindow,
        window.windowID,
        options
    )
}

/// 缩采样为 9x8 灰度矩阵并计算 64-bit 横向差分哈希 dHash64（16 位小写 hex，纯内存计算不落盘）。
/// 先以高质量降采样至 144x128 灰度缓冲，再按 16x16 像素块求和均化为 9x8 亮度矩阵，避免点采样漏掉细文字气泡。
func computeDHash64(_ image: CGImage) -> String {
    let sw = 144
    let sh = 128
    var buf = [UInt8](repeating: 255, count: sw * sh)
    let colorSpace = CGColorSpaceCreateDeviceGray()
    guard let ctx = CGContext(
        data: &buf,
        width: sw,
        height: sh,
        bitsPerComponent: 8,
        bytesPerRow: sw,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.none.rawValue
    ) else {
        return "0000000000000000"
    }
    ctx.setFillColor(gray: 1.0, alpha: 1.0)
    ctx.fill(CGRect(x: 0, y: 0, width: sw, height: sh))
    ctx.interpolationQuality = .high
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: sw, height: sh))

    let width = 9
    let height = 8
    let bx = 16
    let by = 16
    var grid = [Int](repeating: 0, count: width * height)
    for gy in 0..<height {
        for gx in 0..<width {
            var sum = 0
            for dy in 0..<by {
                let rowStart = (gy * by + dy) * sw + gx * bx
                for dx in 0..<bx {
                    sum += Int(buf[rowStart + dx])
                }
            }
            grid[gy * width + gx] = sum
        }
    }

    var hash: UInt64 = 0
    var bitIndex: UInt64 = 63
    for row in 0..<height {
        let rowOffset = row * width
        for col in 0..<(width - 1) {
            if grid[rowOffset + col] > grid[rowOffset + col + 1] {
                hash |= (UInt64(1) << bitIndex)
            }
            if bitIndex > 0 {
                bitIndex -= 1
            }
        }
    }
    return String(format: "%016llx", hash)
}

func captureWindowDHash(_ window: WindowCandidate) -> (dHash64: String, occluded: Bool, captureOk: Bool) {
    guard CGPreflightScreenCaptureAccess(),
          let cgImg = captureWindowImage(window, nominalResolution: true) else {
        return ("", false, false)
    }
    if isImageFullyTransparent(cgImg) {
        return ("", true, false)
    }
    return (computeDHash64(cgImg), false, true)
}

/// 检测图像是否全透明（macOS 对被其他应用完全遮挡的窗口返回 alpha=0 的空图）。
/// 采样网格点，若所有采样点 alpha 都为 0 则判定为遮挡。
func isImageFullyTransparent(_ image: CGImage) -> Bool {
    let w = image.width, h = image.height
    guard w > 8, h > 8 else { return true }
    let sampleW = min(w, 64), sampleH = min(h, 64)
    var pixels = [UInt8](repeating: 0, count: sampleW * sampleH * 4)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(data: &pixels, width: sampleW, height: sampleH,
                              bitsPerComponent: 8, bytesPerRow: sampleW * 4,
                              space: colorSpace,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
        return false
    }
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: sampleW, height: sampleH))
    for i in stride(from: 3, to: pixels.count, by: 4) {
        if pixels[i] != 0 { return false }
    }
    return true
}

func parseTitleFromHeaderOCR(_ window: WindowCandidate) -> String? {
    guard CGPreflightScreenCaptureAccess(),
          let image = captureWindowImage(window) else { return nil }
    let scale = Double(image.width) / max(window.width, 1.0)
    let cropH = min(Double(image.height), max(1.0, 140.0 * scale))
    let cropX = min(Double(image.width) * 0.25, Double(image.width) - 10)
    let cropRect = CGRect(x: cropX, y: 0, width: Double(image.width) - cropX, height: cropH)
    guard let cropped = image.cropping(to: cropRect),
          let results = try? runVisionOCR(cgImage: cropped),
          let first = results.first,
          let text = first["text"] as? String else {
        return nil
    }
    return text
}

// MARK: - Input / CGEvent Helpers

/// 二次贝塞尔轨迹移动（反自动化对抗：模拟真人鼠标轨迹，避免瞬移指纹）。
/// 光标沿带随机控制点的二次贝塞尔曲线分步逼近目标，步数随距离自适应，
/// 每步随机延时 6-18ms，末端两步带轻微手抖。近距离（<12px）直接落点。
func bezierMouseMove(src: CGEventSource?, from: CGPoint, to: CGPoint) {
    let dx = to.x - from.x, dy = to.y - from.y
    let dist = hypot(dx, dy)
    guard dist > 12.0 else {
        if let mv = CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: to, mouseButton: .left) {
            mv.post(tap: .cghidEventTap)
        }
        return
    }
    // 控制点：中点向法线方向随机偏移 12%~30% 距离，保证每次轨迹形状不同
    let mid = CGPoint(x: (from.x + to.x) / 2, y: (from.y + to.y) / 2)
    let bend = dist * Double.random(in: 0.12...0.30) * (Bool.random() ? 1 : -1)
    let angle = atan2(dy, dx) + Double.pi / 2
    let control = CGPoint(x: mid.x + cos(angle) * bend, y: mid.y + sin(angle) * bend)
    let steps = max(8, min(36, Int(dist / 14.0)))
    for i in 1...steps {
        let t = Double(i) / Double(steps)
        let u = 1 - t
        var point = CGPoint(x: u * u * from.x + 2 * u * t * control.x + t * t * to.x,
                            y: u * u * from.y + 2 * u * t * control.y + t * t * to.y)
        // 末端两步轻微手抖（±3px），落点不完美贴合；点击事件仍用精确坐标
        if i >= steps - 2 {
            point.x += Double.random(in: -3.0...3.0)
            point.y += Double.random(in: -3.0...3.0)
        }
        if let mv = CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) {
            mv.post(tap: .cghidEventTap)
        }
        usleep(useconds_t.random(in: 6_000...18_000))
    }
    if let mv = CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: to, mouseButton: .left) {
        mv.post(tap: .cghidEventTap)
    }
}

/// 右键单击（打开微信上下文菜单：语音「转文字」等生态能力入口）
func moveAndRightClick(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)
    var start = point
    if let cur = CGEvent(source: nil)?.location { start = cur }
    bezierMouseMove(src: src, from: start, to: point)
    usleep(30_000 + useconds_t.random(in: 0...30_000))
    if let down = CGEvent(mouseEventSource: src, mouseType: .rightMouseDown, mouseCursorPosition: point, mouseButton: .right),
       let up = CGEvent(mouseEventSource: src, mouseType: .rightMouseUp, mouseCursorPosition: point, mouseButton: .right) {
        down.post(tap: .cghidEventTap)
        usleep(useconds_t.random(in: 30_000...70_000))
        up.post(tap: .cghidEventTap)
    }
}

func cmdRightClick(flags: Set<String>, options: [String: String]) {
    guard CGPreflightPostEventAccess() else {
        failJSON("macOS PostEvent permission not granted.", code: "post_event_permission_denied")
    }
    guard let xStr = options["x"], let yStr = options["y"],
          let x = Double(xStr), let y = Double(yStr) else {
        failJSON("Missing valid --x and --y coordinates", code: "missing_argument")
    }
    moveAndRightClick(x: x, y: y)
    writeJSON(["ok": true, "x": x, "y": y, "rightClick": true])
}

func moveAndClick(x: Double, y: Double, doubleClick: Bool = false) {
    let point = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)
    // 从当前光标位置出发沿贝塞尔轨迹移动（真人移动曲线，而非瞬移）
    var start = point
    if let cur = CGEvent(source: nil)?.location {
        start = cur
    }
    bezierMouseMove(src: src, from: start, to: point)
    usleep(30_000 + useconds_t.random(in: 0...40_000))
    let clicks = doubleClick ? 2 : 1
    for clickState in 1...clicks {
        if let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
           let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) {
            down.setIntegerValueField(.mouseEventClickState, value: Int64(clickState))
            up.setIntegerValueField(.mouseEventClickState, value: Int64(clickState))
            down.post(tap: .cghidEventTap)
            usleep(useconds_t.random(in: 20_000...60_000))
            up.post(tap: .cghidEventTap)
            usleep(useconds_t.random(in: 35_000...70_000))
        }
    }
}

var lastSyntheticKeyTimestamp: CFAbsoluteTime = 0

func humanTypedSinceSyntheticKey(idleLimit: Double) -> (Bool, Double) {
    let hwIdle = hardwareKeyboardIdleSeconds()
    if lastSyntheticKeyTimestamp <= 0 {
        return (hwIdle < idleLimit, hwIdle)
    }
    let elapsed = max(0.0, CFAbsoluteTimeGetCurrent() - lastSyntheticKeyTimestamp)
    let isHuman = (hwIdle + 0.06 < elapsed) && (hwIdle < idleLimit)
    return (isHuman, hwIdle)
}

func postKey(keyCode: CGKeyCode, flags: CGEventFlags = []) {
    let src = CGEventSource(stateID: .privateState)
    if let down = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: true),
       let up = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: false) {
        down.flags = flags
        up.flags = flags
        down.post(tap: .cghidEventTap)
        usleep(20_000)
        up.post(tap: .cghidEventTap)
        lastSyntheticKeyTimestamp = CFAbsoluteTimeGetCurrent()
    }
}

// Keycodes (macOS Carbon HIToolbox US QWERTY virtual keys)
let kKeyA: CGKeyCode = 0
let kKeyC: CGKeyCode = 8
let kKeyV: CGKeyCode = 9
let kKeyReturn: CGKeyCode = 36
let kKeyDelete: CGKeyCode = 51
let kKeyRightArrow: CGKeyCode = 124

func findInputElement(in root: AXUIElement, windowBounds: CGRect? = nil, maxNodes: Int = 2000) -> AXUIElement? {
    var queue = [root]
    var idx = 0
    var bestFallback: AXUIElement?
    var bestScore = -1_000_000.0
    while idx < queue.count && idx < maxNodes {
        let el = queue[idx]
        idx += 1
        let ident = axString(el, kAXIdentifierAttribute) ?? ""
        let role = axString(el, kAXRoleAttribute) ?? ""
        if inputIdentifiers.contains(ident) {
            return el
        }
        if role == kAXTextAreaRole as String || role == kAXTextFieldRole as String {
            var score = (role == kAXTextAreaRole as String) ? 100.0 : 10.0
            if let pt = axPoint(el, kAXPositionAttribute), let sz = axSize(el, kAXSizeAttribute), sz.width >= 60, sz.height >= 16 {
                if let wb = windowBounds {
                    if Double(pt.y) >= Double(wb.minY) + Double(wb.height) * 0.45 {
                        score += 500.0
                    } else if Double(pt.y) < Double(wb.minY) + 125.0 {
                        // Avoid top search bars such as Feishu/DingTalk Cmd+K box
                        score -= 400.0
                    }
                    if Double(pt.x) >= Double(wb.minX) + Double(wb.width) * 0.28 {
                        score += 200.0
                    }
                }
                score += min(300.0, Double(sz.width) * 0.25) + min(150.0, Double(sz.height))
            }
            if score > bestScore {
                bestScore = score
                bestFallback = el
            }
        }
        queue.append(contentsOf: axChildren(el))
    }
    return bestFallback
}

func runOpenAppProcess(kind: AppKind) {
    let resolvedBundleID = kind.bundleIDs.first(where: {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil
    }) ?? kind.bundleID
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    proc.arguments = ["-b", resolvedBundleID]
    proc.standardOutput = FileHandle.nullDevice
    proc.standardError = FileHandle.nullDevice
    try? proc.run()
    proc.waitUntilExit()
}

func axBool(_ element: AXUIElement, _ key: String) -> Bool? {
    guard let raw = axAttr(element, key) else { return nil }
    if let b = raw as? Bool { return b }
    if let n = raw as? NSNumber { return n.boolValue }
    return nil
}

func axUnminimizeAndRaiseAppWindows(pid: pid_t, kind: AppKind = .wechat) -> Bool {
    guard AXIsProcessTrusted() else { return false }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 1.5)
    guard let windows = axAttr(app, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else {
        return false
    }
    var acted = false
    for win in windows {
        if axBool(win, kAXMinimizedAttribute) == true {
            _ = AXUIElementSetAttributeValue(win, kAXMinimizedAttribute as CFString, kCFBooleanFalse)
            acted = true
        }
        let title = axString(win, kAXTitleAttribute) ?? ""
        let sz = axSize(win, kAXSizeAttribute) ?? .zero
        if kind.mainTitles.contains(title) || (sz.width >= 320 && sz.height >= 240) {
            _ = AXUIElementPerformAction(win, kAXRaiseAction as CFString)
            acted = true
        }
    }
    return acted
}

func pressAppWindowMenu(pid: pid_t, kind: AppKind = .wechat) -> Bool {
    guard AXIsProcessTrusted() else { return false }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 1.5)
    guard let menuBarRaw = axAttr(app, kAXMenuBarAttribute) else { return false }
    let menuBar = menuBarRaw as! AXUIElement
    let topItems = axChildren(menuBar)
    for top in topItems {
        let topTitle = axString(top, kAXTitleAttribute) ?? ""
        if topTitle != "窗口" && topTitle != "Window" { continue }
        for subMenu in axChildren(top) {
            for item in axChildren(subMenu) {
                let title = axString(item, kAXTitleAttribute) ?? ""
                if kind.mainTitles.contains(title) || title == "聊天" || title == "前置全部窗口" {
                    if AXUIElementPerformAction(item, kAXPressAction as CFString) == .success {
                        return true
                    }
                }
            }
        }
    }
    return false
}

func findAppDockItem(kind: AppKind = .wechat) -> AXUIElement? {
    guard AXIsProcessTrusted(),
          let dockApp = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.dock").first else {
        return nil
    }
    let dockAX = AXUIElementCreateApplication(dockApp.processIdentifier)
    AXUIElementSetMessagingTimeout(dockAX, 1.5)
    var queue: [AXUIElement] = [dockAX]
    var idx = 0
    while idx < queue.count && idx < 400 {
        let el = queue[idx]
        idx += 1
        let subrole = axString(el, kAXSubroleAttribute) ?? ""
        let title = axString(el, kAXTitleAttribute) ?? ""
        if (subrole == "AXApplicationDockItem" || subrole == "AXMinimizedWindowDockItem") &&
           kind.mainTitles.contains(title) {
            return el
        }
        queue.append(contentsOf: axChildren(el))
    }
    return nil
}

func clickAppInDock(kind: AppKind = .wechat) -> String? {
    guard let dockItem = findAppDockItem(kind: kind) else { return nil }
    if AXUIElementPerformAction(dockItem, kAXPressAction as CFString) == .success {
        return "dock_ax_press"
    }
    if CGPreflightPostEventAccess(),
       let pt = axPoint(dockItem, kAXPositionAttribute),
       let sz = axSize(dockItem, kAXSizeAttribute),
       sz.width > 0 && sz.height > 0 {
        moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
        return "dock_cgevent_click"
    }
    return nil
}

/// Ensures target app (WeChat or WeCom) is running, unminimized, visible as an on-screen window, and frontmost.
func ensureAppMainWindow(kind: AppKind = .wechat) -> (app: NSRunningApplication?, windows: [WindowCandidate], recoveryMethod: String?) {
    var recoveryMethod: String? = nil
    var app = findBestRunningApp(for: kind)

    // Stage 1: Launch target app via bundle ID if not running
    if app == nil {
        runOpenAppProcess(kind: kind)
        for _ in 0..<12 {
            usleep(250_000)
            app = findBestRunningApp(for: kind)
            if app != nil { break }
        }
        if app != nil { recoveryMethod = "open_launch" }
    }
    guard let runningApp = app else {
        return (nil, [], nil)
    }

    var windows = listWindows(for: kind)
    if windows.isEmpty {
        // Stage 2: Unhide + Activate + AX Unminimize & Raise
        _ = runningApp.unhide()
        _ = runningApp.activate(options: [.activateIgnoringOtherApps])
        if axUnminimizeAndRaiseAppWindows(pid: runningApp.processIdentifier, kind: kind) {
            usleep(350_000)
            windows = listWindows(for: kind)
            if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? "ax_unminimize"
            }
        }
    }

    if windows.isEmpty {
        // Stage 3a: `/usr/bin/open -b <bundleID>` (triggers macOS Reopen Application AppleEvent)
        runOpenAppProcess(kind: kind)
        usleep(400_000)
        windows = listWindows(for: kind)
        if !windows.isEmpty {
            recoveryMethod = recoveryMethod ?? "open_reopen"
        }
    }

    if windows.isEmpty {
        // Stage 3b: Trigger app menu bar "窗口" -> main title/"聊天"
        _ = runningApp.activate(options: [.activateIgnoringOtherApps])
        usleep(180_000)
        if pressAppWindowMenu(pid: runningApp.processIdentifier, kind: kind) {
            usleep(350_000)
            windows = listWindows(for: kind)
            if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? "menu_bar_window"
            }
        }
    }

    if windows.isEmpty {
        // Stage 4: Find & click Dock icon (AXPress first, then physical CGEvent click)
        if let dockMethod = clickAppInDock(kind: kind) {
            usleep(450_000)
            windows = listWindows(for: kind)
            if windows.isEmpty, let dockItem = findAppDockItem(kind: kind), CGPreflightPostEventAccess(),
               let pt = axPoint(dockItem, kAXPositionAttribute),
               let sz = axSize(dockItem, kAXSizeAttribute),
               sz.width > 0 && sz.height > 0 {
                moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
                usleep(450_000)
                windows = listWindows(for: kind)
                if !windows.isEmpty { recoveryMethod = "dock_cgevent_click" }
            } else if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? dockMethod
            }
        }
    }

    _ = runningApp.activate(options: [.activateIgnoringOtherApps])
    usleep(220_000)
    if windows.isEmpty {
        windows = listWindows(for: kind)
    }
    return (runningApp, windows, recoveryMethod)
}

func ensureWeChatMainWindow() -> (app: NSRunningApplication?, windows: [WindowCandidate], recoveryMethod: String?) {
    return ensureAppMainWindow(kind: .wechat)
}

// MARK: - Subcommands

func cmdStatus(flags: Set<String> = [], options: [String: String] = [:]) {
    let (requestedApp, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: false)
    let axTrusted = AXIsProcessTrusted()
    let scTrusted = CGPreflightScreenCaptureAccess()
    let postTrusted = CGPreflightPostEventAccess()
    let (frontOK, frontDesc) = isAppFrontmost(targetKind)
    let app = findBestRunningApp(for: targetKind)

    let mainTop = NSScreen.screens.first { $0.frame.contains(NSPoint.zero) }?.frame.maxY ?? NSScreen.main?.frame.maxY ?? 0
    let screenList: [[String: Any]] = NSScreen.screens.map { scr in
        let f = scr.frame
        let vf = scr.visibleFrame
        return [
            "x": f.minX,
            "y": mainTop - f.maxY,
            "width": f.width,
            "height": f.height,
            "visibleX": vf.minX,
            "visibleY": mainTop - vf.maxY,
            "visibleWidth": vf.width,
            "visibleHeight": vf.height,
            "isMain": scr == NSScreen.main,
        ]
    }

    var payload: [String: Any] = [
        "ok": true,
        "reviewedSendProtocol": 1,
        "appId": targetKind.appId,
        "appLabel": targetKind.appLabel,
        "appBundleID": app?.bundleIdentifier ?? targetKind.bundleID,
        "appRunning": app != nil,
        "appFrontmost": frontOK,
        "accessibilityTrusted": axTrusted,
        "postEventTrusted": postTrusted,
        "screenCaptureTrusted": scTrusted,
        "wechatRunning": app != nil,
        "wechatFrontmost": frontOK,
        "frontmostApp": frontDesc,
        "hidIdle": queryHIDIdleState(),
        "screens": screenList,
    ]
    if requestedApp != "default" {
        payload["requestedApp"] = requestedApp
        payload["resolvedApp"] = targetKind.appId
    }

    if let app = app {
        payload["wechatPID"] = app.processIdentifier
        payload["appPID"] = app.processIdentifier
        payload["wechatBundleID"] = app.bundleIdentifier ?? targetKind.bundleID
        let windows = listWindows(for: targetKind)
        payload["windowCount"] = windows.count
        payload["windows"] = windows.map { $0.toDict() }

        if flags.contains("with-chat-title") {
            let axTitle: (name: String?, memberCount: Int?) = (targetKind == .wechat) ? readChatTitleFromAX(pid: app.processIdentifier) : (name: nil, memberCount: nil)
            if let name = axTitle.name {
                payload["currentChatTitle"] = name
                payload["currentChatSource"] = "accessibility"
                if let count = axTitle.memberCount {
                    payload["currentChatMemberCount"] = count
                }
            } else if let mainWin = selectTargetWindow(in: windows, options: options),
                      let ocrTitle = parseTitleFromHeaderOCR(mainWin) {
                payload["currentChatTitle"] = ocrTitle
                payload["currentChatSource"] = "vision_ocr"
            }
        }
    }

    writeJSON(payload)
}

private func scanAppsAndWindows(options: [String: String]) -> (
    requestedApp: String,
    resolvedApp: String?,
    appsOut: [[String: Any]],
    windows: [WindowCandidate]
) {
    let rawApp = (options["app"] ?? "all").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let kinds: [AppKind]
    var resolvedApp: String? = nil
    switch rawApp {
    case "", "all":
        kinds = [.wechat, .wecom]
    case "omni", "channels":
        kinds = AppKind.allCases
    case "auto":
        let autoKind = resolveAutoApp(options: options)
        kinds = [autoKind]
        resolvedApp = autoKind.appId
    default:
        if let explicit = AppKind.fromCLI(rawApp) {
            kinds = [explicit]
            resolvedApp = explicit.appId
        } else {
            failJSON("Unsupported --app value '\(rawApp)'. Expected wechat|wecom|feishu|dingtalk|xiaohongshu|douyin|all|omni|auto.", code: "invalid_argument")
        }
    }

    let rawList = copyOnScreenWindowInfo()
    var appsOut: [[String: Any]] = []
    var windows: [WindowCandidate] = []

    for kind in kinds {
        let runningApps = findRunningApps(for: kind)
        let bestApp = findBestRunningApp(for: kind)
        let wins = listAppWindows(for: kind, apps: runningApps, rawWindowList: rawList)
        let (frontOK, _) = isAppFrontmost(kind)
        var appDict: [String: Any] = [
            "appId": kind.appId,
            "appLabel": kind.appLabel,
            "bundleID": bestApp?.bundleIdentifier ?? kind.bundleID,
            "running": bestApp != nil,
            "frontmost": frontOK,
            "windowCount": wins.count,
        ]
        if let best = bestApp {
            appDict["pid"] = Int(best.processIdentifier)
            if let locName = best.localizedName, !locName.isEmpty {
                appDict["localizedName"] = locName
            }
        }
        appsOut.append(appDict)
        windows.append(contentsOf: wins)
    }

    return (rawApp.isEmpty ? "all" : rawApp, resolvedApp, appsOut, windows)
}

func cmdListAppWindows(flags: Set<String> = [], options: [String: String]) {
    let scan = scanAppsAndWindows(options: options)
    let withDHash = flags.contains("with-dhash")
        || ["1", "true", "yes"].contains((options["with-dhash"] ?? "").lowercased())

    let t0 = DispatchTime.now()
    let windowsOut: [[String: Any]] = scan.windows.map { win in
        var dict = win.toDict()
        if withDHash {
            let dh = captureWindowDHash(win)
            dict["dHash64"] = dh.dHash64
            dict["captureOk"] = dh.captureOk
            dict["occluded"] = dh.occluded
        }
        return dict
    }

    var payload: [String: Any] = [
        "ok": true,
        "requestedApp": scan.requestedApp,
        "apps": scan.appsOut,
        "windowCount": windowsOut.count,
        "windows": windowsOut,
    ]
    if withDHash {
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1_000_000.0
        payload["withDHash"] = true
        payload["dhashElapsedMs"] = (elapsedMs * 10.0).rounded() / 10.0
    }
    if let resolved = scan.resolvedApp {
        payload["resolvedApp"] = resolved
    }
    writeJSON(payload)
}

func cmdDHashWindows(options: [String: String]) {
    guard CGPreflightScreenCaptureAccess() else {
        failJSON("Screen Recording permission (CGPreflightScreenCaptureAccess) is not granted.", code: "screen_capture_denied")
    }
    let t0 = DispatchTime.now()
    let scan = scanAppsAndWindows(options: options)
    let windowsOut: [[String: Any]] = scan.windows.map { win in
        let dh = captureWindowDHash(win)
        var dict = win.toDict()
        dict["dHash64"] = dh.dHash64
        dict["captureOk"] = dh.captureOk
        dict["occluded"] = dh.occluded
        return dict
    }
    let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1_000_000.0
    var payload: [String: Any] = [
        "ok": true,
        "app": scan.requestedApp,
        "requestedApp": scan.requestedApp,
        "count": windowsOut.count,
        "elapsedMs": (elapsedMs * 10.0).rounded() / 10.0,
        "windows": windowsOut,
    ]
    if let resolved = scan.resolvedApp {
        payload["resolvedApp"] = resolved
    }
    writeJSON(payload)
}

func cmdAXTree(options: [String: String]) {
    guard AXIsProcessTrusted() else {
        failJSON("Accessibility permission (AXIsProcessTrusted) is not granted.", code: "ax_permission_denied")
    }
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    guard let app = findBestRunningApp(for: targetKind) else {
        failJSON("\(targetKind.appLabel) (\(targetKind.bundleID)) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    let windows = listWindows(for: targetKind)
    let targetWin = (options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty)
        ? selectTargetWindow(in: windows, options: options)
        : nil
    let pid = targetWin?.pid ?? app.processIdentifier
    enableElectronAccessibility(pid: pid, kind: targetKind)
    guard let win = findAXWindow(pid: pid, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]) else {
        failJSON("No accessible \(targetKind.appLabel) window found.", code: "no_ax_window", extra: ["appId": targetKind.appId])
    }

    let maxDepth = Int(options["depth"] ?? "8") ?? 8
    let maxNodes = Int(options["max-nodes"] ?? "1200") ?? 1200

    var nodes: [[String: Any]] = []
    var sessionItems: [[String: Any]] = []
    var messageItems: [[String: Any]] = []
    var inputElements: [[String: Any]] = []
    var currentChat: [String: Any] = [:]

    var stack: [(el: AXUIElement, depth: Int, inMsgList: Bool)] = [(win, 0, false)]
    while !stack.isEmpty && nodes.count < maxNodes {
        let item = stack.removeFirst()
        let el = item.el
        let depth = item.depth
        let role = axString(el, kAXRoleAttribute) ?? ""
        let subrole = axString(el, kAXSubroleAttribute) ?? ""
        let ident = axString(el, kAXIdentifierAttribute) ?? ""
        let title = axString(el, kAXTitleAttribute) ?? ""
        let desc = axString(el, kAXDescriptionAttribute) ?? ""
        let value = axString(el, kAXValueAttribute) ?? ""
        let pt = axPoint(el, kAXPositionAttribute)
        let sz = axSize(el, kAXSizeAttribute)

        let inMsgList = item.inMsgList || ident == "chat_message_list"

        var node: [String: Any] = [
            "depth": depth,
            "role": role,
        ]
        if !subrole.isEmpty { node["subrole"] = subrole }
        if !ident.isEmpty { node["identifier"] = ident }
        if !title.isEmpty { node["title"] = title }
        if !desc.isEmpty { node["description"] = desc }
        if !value.isEmpty { node["value"] = value }
        if let pt = pt, let sz = sz {
            node["bounds"] = ["x": pt.x, "y": pt.y, "width": sz.width, "height": sz.height]
            node["center"] = ["x": pt.x + sz.width / 2.0, "y": pt.y + sz.height / 2.0]
        }

        if !ident.isEmpty || !title.isEmpty || !value.isEmpty || !desc.isEmpty || role == kAXTextAreaRole as String {
            nodes.append(node)
        }

        if ident == "current_chat_name_label" && !value.isEmpty {
            currentChat["name"] = value
        } else if ident == "current_chat_count_label" && !value.isEmpty {
            currentChat["memberCount"] = Int(value.filter { $0.isNumber }) ?? 0
        }

        if ident.hasPrefix("session_item_") {
            sessionItems.append(node)
        } else if inMsgList && (!value.isEmpty || !title.isEmpty || !desc.isEmpty) && ident != "chat_message_list" {
            messageItems.append(node)
        }

        if inputIdentifiers.contains(ident) || role == kAXTextAreaRole as String {
            inputElements.append(node)
        }

        if depth < maxDepth {
            for child in axChildren(el) {
                stack.append((child, depth + 1, inMsgList))
            }
        }
    }

    writeJSON([
        "ok": true,
        "appId": targetKind.appId,
        "appLabel": targetKind.appLabel,
        "wechatPID": pid,
        "currentChat": currentChat,
        "sessionItems": sessionItems,
        "messageItems": messageItems,
        "inputElements": inputElements,
        "nodeCount": nodes.count,
        "nodes": nodes,
    ])
}

func cmdOCR(options: [String: String]) {
    guard let imgPath = options["image"] else {
        failJSON("Missing --image <path>", code: "missing_argument")
    }
    guard FileManager.default.fileExists(atPath: imgPath) else {
        failJSON("Image file not found: \(imgPath)", code: "file_not_found")
    }
    guard let loadedImage = loadCGImage(at: imgPath) else {
        failJSON("Unable to decode image: \(imgPath)", code: "invalid_image")
    }

    var targetImage = loadedImage
    if let cropSpec = options["crop"] {
        let nums = cropSpec.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        if nums.count == 4 {
            let maxW = Double(loadedImage.width)
            let maxH = Double(loadedImage.height)
            let cx = max(0.0, min(maxW - 1.0, nums[0]))
            let cy = max(0.0, min(maxH - 1.0, nums[1]))
            let cw = max(1.0, min(maxW - cx, nums[2]))
            let ch = max(1.0, min(maxH - cy, nums[3]))
            if let cropped = loadedImage.cropping(to: CGRect(x: cx, y: cy, width: cw, height: ch)) {
                targetImage = cropped
            }
        }
    }

    var savedCropPath: String? = nil
    if let outPath = options["out"], !outPath.isEmpty {
        if saveCGImageAsPNG(targetImage, to: outPath) {
            savedCropPath = outPath
        }
    }

    let langsRaw = options["langs"] ?? "zh-Hans,en-US"
    let langs = langsRaw.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }

    let t0 = DispatchTime.now()
    do {
        let elements = try runVisionOCR(cgImage: targetImage, languages: langs)
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1_000_000.0
        var resp: [String: Any] = [
            "ok": true,
            "imagePath": imgPath,
            "imageWidth": targetImage.width,
            "imageHeight": targetImage.height,
            "elapsedMs": (elapsedMs * 10.0).rounded() / 10.0,
            "count": elements.count,
            "elements": elements,
        ]
        if let saved = savedCropPath {
            resp["savedPath"] = saved
        }
        writeJSON(resp)
    } catch {
        failJSON("Vision OCR failed: \(error.localizedDescription)", code: "vision_ocr_failed")
    }
}

func cmdCaptureOCR(options: [String: String], allowActivation: Bool = true) {
    guard CGPreflightScreenCaptureAccess() else {
        failJSON("Screen Recording permission (CGPreflightScreenCaptureAccess) is not granted.", code: "screen_capture_denied")
    }
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let reqWindowID = options["window-id"].flatMap { UInt32($0) }
    let reqWindowTitle = options["window-title"]?.trimmingCharacters(in: .whitespacesAndNewlines)

    var app = findBestRunningApp(for: targetKind)
    var windows: [WindowCandidate] = app != nil ? listWindows(for: targetKind) : []
    if allowActivation && (app == nil || (reqWindowID == nil && (reqWindowTitle == nil || reqWindowTitle!.isEmpty) && windows.isEmpty)) {
        let ensured = ensureAppMainWindow(kind: targetKind)
        app = ensured.app
        if !ensured.windows.isEmpty {
            windows = ensured.windows
        } else if app != nil {
            windows = listWindows(for: targetKind)
        }
    }
    guard app != nil else {
        failJSON("\(targetKind.appLabel) is not running and could not be launched.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    if windows.isEmpty {
        windows = listWindows(for: targetKind)
    }

    let targetWin = selectTargetWindow(in: windows, options: options)

    guard let mainWin = targetWin else {
        failJSON(
            "No matching visible \(targetKind.appLabel) window found.",
            code: (reqWindowID != nil || reqWindowTitle != nil) ? "window_not_found" : "no_window",
            extra: [
                "appId": targetKind.appId,
                "availableWindows": windows.map { $0.toDict() }
            ]
        )
    }
    guard let cgImage = captureWindowImage(mainWin) else {
        failJSON("CGWindowListCreateImage returned nil.", code: "capture_failed")
    }
    // 遮挡检测：macOS 对被其他应用完全遮挡的窗口返回全透明图（alpha=0），OCR 必然为空。
    // 明确报 window_occluded，让上层区分「窗口被遮挡」与「OCR 真失败」。
    if isImageFullyTransparent(cgImage) {
        failJSON(
            "\(targetKind.appLabel) window is fully occluded by another app (macOS returns a transparent image). Bring \(targetKind.appLabel) to front or minimize the covering window.",
            code: "window_occluded",
            extra: ["appId": targetKind.appId, "windowID": mainWin.windowID]
        )
    }

    var savedPath: String? = nil
    if let outPath = options["out"] {
        if saveCGImageAsPNG(cgImage, to: outPath) {
            savedPath = outPath
        }
    }

    let t0 = DispatchTime.now()
    do {
        let elements = try runVisionOCR(cgImage: cgImage)
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1_000_000.0
        var resp: [String: Any] = [
            "ok": true,
            "appId": targetKind.appId,
            "appLabel": targetKind.appLabel,
            "bundleID": mainWin.bundleID,
            "pid": Int(mainWin.pid),
            "isMainWindow": mainWin.isMainWindow,
            "windowID": mainWin.windowID,
            "windowTitle": mainWin.title,
            "windowBounds": ["x": mainWin.x, "y": mainWin.y, "width": mainWin.width, "height": mainWin.height],
            "imageWidth": cgImage.width,
            "imageHeight": cgImage.height,
            "elapsedMs": (elapsedMs * 10.0).rounded() / 10.0,
            "count": elements.count,
            "elements": elements,
        ]
        if let saved = savedPath {
            resp["savedPath"] = saved
        }
        writeJSON(resp)
    } catch {
        failJSON("Vision OCR failed: \(error.localizedDescription)", code: "vision_ocr_failed")
    }
}

func cmdSetWindowFrame(options: [String: String]) {
    guard AXIsProcessTrusted() else {
        failJSON("Accessibility permission (AXIsProcessTrusted) is not granted.", code: "ax_permission_denied")
    }
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    guard let app = findBestRunningApp(for: targetKind) else {
        failJSON("\(targetKind.appLabel) (\(targetKind.bundleID)) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    let windows = listWindows(for: targetKind)
    let matchedWin = (options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty)
        ? selectTargetWindow(in: windows, options: options)
        : nil
    let pid = matchedWin?.pid ?? app.processIdentifier
    let targetWin = findAXWindow(pid: pid, kind: targetKind, targetWin: matchedWin, reqTitle: options["window-title"])
    guard let win = targetWin else {
        failJSON("No matching accessible \(targetKind.appLabel) window found.", code: "no_ax_window", extra: ["appId": targetKind.appId])
    }

    let curPt = axPoint(win, kAXPositionAttribute) ?? .zero
    let curSz = axSize(win, kAXSizeAttribute) ?? .zero
    var newPt = CGPoint(
        x: options["x"].flatMap { Double($0) } ?? Double(curPt.x),
        y: options["y"].flatMap { Double($0) } ?? Double(curPt.y)
    )
    var newSz = CGSize(
        width: options["width"].flatMap { Double($0) } ?? Double(curSz.width),
        height: options["height"].flatMap { Double($0) } ?? Double(curSz.height)
    )

    var posErrRaw: Int32 = 0
    var sizeErrRaw: Int32 = 0
    if let axPos = AXValueCreate(.cgPoint, &newPt) {
        posErrRaw = AXUIElementSetAttributeValue(win, kAXPositionAttribute as CFString, axPos).rawValue
    }
    if let axSz = AXValueCreate(.cgSize, &newSz) {
        sizeErrRaw = AXUIElementSetAttributeValue(win, kAXSizeAttribute as CFString, axSz).rawValue
    }
    usleep(80_000)
    // Apply position a second time in case min-size clamping shifted origin
    if let axPos2 = AXValueCreate(.cgPoint, &newPt) {
        _ = AXUIElementSetAttributeValue(win, kAXPositionAttribute as CFString, axPos2)
    }
    usleep(50_000)

    let actualPt = axPoint(win, kAXPositionAttribute) ?? newPt
    let actualSz = axSize(win, kAXSizeAttribute) ?? newSz
    let winTitle = axString(win, kAXTitleAttribute) ?? ""
    writeJSON([
        "ok": posErrRaw == 0 || sizeErrRaw == 0,
        "windowTitle": winTitle,
        "posError": posErrRaw,
        "sizeError": sizeErrRaw,
        "requestedFrame": ["x": newPt.x, "y": newPt.y, "width": newSz.width, "height": newSz.height],
        "actualFrame": ["x": actualPt.x, "y": actualPt.y, "width": actualSz.width, "height": actualSz.height],
    ])
}

func cmdRenderTestImage(options: [String: String]) {
    guard let outPath = options["out"] else {
        failJSON("Missing --out <png_path>", code: "missing_argument")
    }
    let text = options["text"] ?? "客户A-私域运营群 (128)\n你好，请问今年的新品报价单发我一下\n收到，马上为您安排产品资料。"
    let lines = text.components(separatedBy: "\\n").flatMap { $0.components(separatedBy: "\n") }

    let width = 900
    let height = 420
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        failJSON("Failed to allocate NSBitmapImageRep", code: "bitmap_alloc_failed")
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()

    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 28, weight: .medium),
        .foregroundColor: NSColor.black,
    ]
    for (idx, line) in lines.enumerated() {
        let yPos = CGFloat(height - 70 - idx * 64)
        if yPos < 20 { break }
        let attrStr = NSAttributedString(string: line, attributes: attrs)
        attrStr.draw(at: NSPoint(x: 40, y: yPos))
    }

    NSGraphicsContext.restoreGraphicsState()

    guard let pngData = rep.representation(using: .png, properties: [:]) else {
        failJSON("Failed to encode PNG", code: "png_encode_failed")
    }
    do {
        try pngData.write(to: URL(fileURLWithPath: outPath))
        writeJSON([
            "ok": true,
            "outPath": outPath,
            "width": width,
            "height": height,
            "lines": lines,
        ])
    } catch {
        failJSON("Failed to write PNG: \(error.localizedDescription)", code: "write_failed")
    }
}

func cmdClick(flags: Set<String>, options: [String: String]) {
    guard CGPreflightPostEventAccess() else {
        failJSON("macOS Accessibility/PostEvent permission (CGPreflightPostEventAccess) is not granted.", code: "post_event_permission_denied")
    }
    guard let xStr = options["x"], let yStr = options["y"],
          let x = Double(xStr), let y = Double(yStr) else {
        failJSON("Missing valid --x and --y coordinates", code: "missing_argument")
    }
    let dbl = flags.contains("double")
    moveAndClick(x: x, y: y, doubleClick: dbl)
    writeJSON([
        "ok": true,
        "x": x,
        "y": y,
        "doubleClick": dbl,
    ])
}

func scrollWheelAtScreenPoint(_ point: CGPoint, dy: Int32, usePixels: Bool = true, steps: Int = 5) {
    let src = CGEventSource(stateID: .hidSystemState)
    if let move = CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) {
        move.post(tap: .cghidEventTap)
    }
    usleep(40_000)
    let clampedSteps = max(1, min(30, steps))
    let units: CGScrollEventUnit = usePixels ? .pixel : .line
    if clampedSteps == 1 {
        guard let wheel = CGEvent(scrollWheelEvent2Source: src, units: units, wheelCount: 1, wheel1: dy, wheel2: 0, wheel3: 0) else {
            failJSON("Failed to construct CGEvent scroll wheel event.", code: "scroll_event_failed")
        }
        wheel.location = point
        wheel.post(tap: .cghidEventTap)
        return
    }
    let baseStep = dy / Int32(clampedSteps)
    var remainder = dy - (baseStep * Int32(clampedSteps))
    for _ in 0..<clampedSteps {
        var stepDy = baseStep
        if remainder > 0 {
            stepDy += 1
            remainder -= 1
        } else if remainder < 0 {
            stepDy -= 1
            remainder += 1
        }
        if stepDy == 0 {
            continue
        }
        guard let wheel = CGEvent(scrollWheelEvent2Source: src, units: units, wheelCount: 1, wheel1: stepDy, wheel2: 0, wheel3: 0) else {
            failJSON("Failed to construct CGEvent scroll wheel event.", code: "scroll_event_failed")
        }
        wheel.location = point
        wheel.post(tap: .cghidEventTap)
        usleep(18_000)
    }
}

func cmdScroll(options: [String: String]) {
    guard CGPreflightPostEventAccess() else {
        failJSON("macOS Accessibility/PostEvent permission (CGPreflightPostEventAccess) is not granted.", code: "post_event_permission_denied")
    }
    var xOpt = options["x"].flatMap { Double($0) }
    var yOpt = options["y"].flatMap { Double($0) }
    var usedRelative = false
    if (xOpt == nil || yOpt == nil),
       let rxStr = options["rx"], let ryStr = options["ry"],
       let rx = Double(rxStr), let ry = Double(ryStr) {
        let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
        var windows = listWindows(for: targetKind)
        if windows.isEmpty {
            windows = ensureAppMainWindow(kind: targetKind).windows
        }
        guard let win = selectTargetWindow(in: windows, options: options) else {
            failJSON("No visible \(targetKind.appLabel) window for relative scroll.", code: "no_visible_wechat_window", extra: ["appId": targetKind.appId])
        }
        xOpt = win.x + rx * win.width
        yOpt = win.y + ry * win.height
        usedRelative = true
    }
    guard let x = xOpt, let y = yOpt else {
        failJSON("Missing valid --x/--y or --rx/--ry coordinates", code: "missing_argument")
    }
    let dy = Int32(options["dy"] ?? (usedRelative ? "-360" : "-5")) ?? (usedRelative ? -360 : -5)
    let unitStr = (options["units"] ?? (usedRelative ? "pixel" : "line")).lowercased()
    let usePixels = (unitStr == "pixel" || unitStr == "pixels")
    let defaultSteps = usePixels ? 5 : 1
    let steps = Int(options["steps"] ?? "\(defaultSteps)") ?? defaultSteps
    let point = CGPoint(x: x, y: y)
    scrollWheelAtScreenPoint(point, dy: dy, usePixels: usePixels, steps: steps)
    writeJSON([
        "ok": true,
        "x": x,
        "y": y,
        "dy": Int(dy),
        "units": usePixels ? "pixel" : "line",
        "steps": max(1, min(30, steps)),
        "usedRelative": usedRelative,
    ])
}

func cmdActivate(options: [String: String] = [:]) {
    let (requestedApp, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let ensured = ensureAppMainWindow(kind: targetKind)
    guard let app = ensured.app else {
        failJSON("\(targetKind.appLabel) is not running and could not be launched.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    var windows = ensured.windows.isEmpty ? listWindows(for: targetKind) : ensured.windows
    let hasWindowSelector = options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty
    let selectedWin = hasWindowSelector ? selectTargetWindow(in: windows, options: options) : nil
    if let targetWin = selectedWin,
       let targetRunningApp = NSRunningApplication(processIdentifier: targetWin.pid) {
        _ = targetRunningApp.unhide()
        _ = targetRunningApp.activate(options: [.activateIgnoringOtherApps])
        if let axWin = findAXWindow(pid: targetWin.pid, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]) {
            _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
            _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
        }
    } else {
        _ = app.activate(options: [.activateIgnoringOtherApps])
    }
    usleep(200_000)
    let (frontOK, frontDesc) = isAppFrontmost(targetKind)
    windows = listWindows(for: targetKind)
    var resp: [String: Any] = [
        "ok": frontOK && !windows.isEmpty && (!hasWindowSelector || selectedWin != nil),
        "appId": targetKind.appId,
        "appLabel": targetKind.appLabel,
        "bundleID": app.bundleIdentifier ?? targetKind.bundleID,
        "activatedCall": true,
        "appFrontmost": frontOK,
        "appPID": app.processIdentifier,
        "wechatFrontmost": frontOK,
        "frontmostApp": frontDesc,
        "wechatPID": app.processIdentifier,
        "windowCount": windows.count,
        "windows": windows.map { $0.toDict() },
    ]
    if requestedApp != "default" {
        resp["requestedApp"] = requestedApp
        resp["resolvedApp"] = targetKind.appId
    }
    if let sel = selectedWin {
        resp["targetWindowID"] = sel.windowID
        resp["targetWindowTitle"] = sel.title
    }
    if let method = ensured.recoveryMethod {
        resp["recoveryMethod"] = method
    }
    let exitOK = frontOK && !windows.isEmpty && (!hasWindowSelector || selectedWin != nil)
    writeJSON(resp, exitCode: exitOK ? 0 : 1)
}

func cmdRequestPermissions(flags: Set<String>) {
    let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
    let options = [promptKey: true] as CFDictionary
    let axTrusted = AXIsProcessTrustedWithOptions(options)
    let postEventTrusted = CGRequestPostEventAccess()
    let screenCaptureTrusted = CGPreflightScreenCaptureAccess() ? true : CGRequestScreenCaptureAccess()

    let settingsURL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    let shouldOpenSettings = !flags.contains("no-settings")
    var openedSystemSettings = false
    if shouldOpenSettings && (!axTrusted || !postEventTrusted), let url = URL(string: settingsURL) {
        openedSystemSettings = NSWorkspace.shared.open(url)
    }

    writeJSON([
        "ok": true,
        "accessibilityTrusted": axTrusted,
        "postEventTrusted": postEventTrusted,
        "screenCaptureTrusted": screenCaptureTrusted,
        "openedSystemSettings": openedSystemSettings,
        "settingsURL": settingsURL,
        "promptTriggered": true,
    ])
}

func cmdFocusInput(options: [String: String] = [:]) {
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let ensured = ensureAppMainWindow(kind: targetKind)
    guard let app = ensured.app else {
        failJSON("\(targetKind.appLabel) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    let windows = listWindows(for: targetKind)
    let targetWin = selectTargetWindow(in: windows, options: options)
    let targetPID = targetWin?.pid ?? app.processIdentifier
    if let axWin = findAXWindow(pid: targetPID, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]),
       let inputEl = findInputElement(in: axWin, windowBounds: targetWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) }) {
        let focusErr = AXUIElementSetAttributeValue(inputEl, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let pt = axPoint(inputEl, kAXPositionAttribute)
        let sz = axSize(inputEl, kAXSizeAttribute)
        if let pt = pt, let sz = sz {
            let cx = pt.x + sz.width / 2.0
            let cy = pt.y + sz.height / 2.0
            moveAndClick(x: cx, y: cy)
            writeJSON([
                "ok": true,
                "appId": targetKind.appId,
                "method": "ax_and_click",
                "axFocusErr": focusErr.rawValue,
                "clickPoint": ["x": cx, "y": cy],
            ])
        } else if focusErr == .success {
            writeJSON(["ok": true, "appId": targetKind.appId, "method": "ax_focus_only"])
        }
    }

    // Fallback to window bottom-center heuristic (dead-center in input box above bottom toolbar)
    guard let win = targetWin ?? windows.first else {
        failJSON("No \(targetKind.appLabel) window found to focus input.", code: "no_window", extra: ["appId": targetKind.appId])
    }
    let cx = win.x + win.width * 0.60
    let cy = win.y + win.height - 85.0
    moveAndClick(x: cx, y: cy)
    writeJSON([
        "ok": true,
        "appId": targetKind.appId,
        "windowID": win.windowID,
        "method": "window_geometry_fallback",
        "clickPoint": ["x": cx, "y": cy],
    ])
}

// Human-reviewed send: never navigate, use cursor geometry, or append to a user draft.
func cmdReviewedSend(text: String, expectedID: UInt32, expectedTitle: String, kind: AppKind = .wechat) {
    guard AXIsProcessTrusted(), CGPreflightPostEventAccess() else {
        failJSON("\(kind.appLabel) input permissions required.", code: "review_ax_denied")
    }
    guard let app = findBestRunningApp(for: kind) else {
        failJSON("\(kind.appLabel) window changed.", code: "review_target_changed")
    }
    let pid = app.processIdentifier
    func sameChat() -> Bool {
        let windows = listWindows(for: kind, pid: pid)
        guard windows.count == 1, let win = windows.first, win.windowID == expectedID else { return false }
        if kind == .wechat, let title = readChatTitleFromAX(pid: pid).name { return title == expectedTitle }
        guard CGPreflightScreenCaptureAccess(), let img = captureWindowImage(win) else { return false }
        let sx = Double(img.width) / win.width
        let sy = Double(img.height) / win.height
        let split = max(218.0, min(310.0, win.width * 0.38)) + 4.0
        guard let items = try? runVisionOCR(cgImage: img) else { return false }
        let header = items.compactMap { item -> (Double, Double, String)? in
            guard let pt = item["center"] as? [String: Int],
                  let x = pt["x"], let y = pt["y"], let txt = item["text"] as? String,
                  Double(x) / sx > split, (6.0...46.0).contains(Double(y) / sy) else { return nil }
            return (Double(y), Double(x), txt)
        }.sorted { ($0.0, $0.1) < ($1.0, $1.1) }.map { $0.2 }.joined(separator: " ")
        return header.trimmingCharacters(in: .whitespacesAndNewlines) == expectedTitle
    }
    guard sameChat() else { failJSON("\(kind.appLabel) conversation changed.", code: "review_target_changed") }
    _ = app.activate(options: [.activateIgnoringOtherApps])
    usleep(200_000)
    guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid, sameChat(),
          let axWindow = findMainAXWindow(pid: pid, kind: kind), let input = findInputElement(in: axWindow),
          let ident = axString(input, kAXIdentifierAttribute), inputIdentifiers.contains(ident) else {
        failJSON("Cannot verify the current chat input.", code: "review_no_input")
    }
    guard axString(input, kAXValueAttribute) == "" else {
        failJSON("There is already text in the chat input.", code: "review_input_busy")
    }
    let axApp = AXUIElementCreateApplication(pid)
    func inputIsFocused() -> Bool {
        guard let focused = axAttr(axApp, kAXFocusedUIElementAttribute) else { return false }
        return CFEqual(focused, input)
    }
    guard AXUIElementSetAttributeValue(input, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success,
          inputIsFocused(),
          AXUIElementSetAttributeValue(input, kAXValueAttribute as CFString, text as CFString) == .success,
          axString(input, kAXValueAttribute) == text else {
        failJSON("Could not verify exact outgoing text.", code: "review_readback_mismatch")
    }
    // Revalidate after staging, before targeting Return to this specific process.
    guard sameChat(), NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
          inputIsFocused(), axString(input, kAXValueAttribute) == text else {
        failJSON("Chat or input changed before Return.", code: "review_target_changed")
    }
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: kKeyReturn, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: kKeyReturn, keyDown: false) else {
        failJSON("Could not construct send event.", code: "review_readback_mismatch")
    }
    down.postToPid(pid)
    up.postToPid(pid)
    usleep(350_000)
    writeJSON(["ok": true, "verified": true, "sent": true, "readbackSource": "ax_exact"])
}

func cmdPasteAndVerify(flags: Set<String>, options: [String: String]) {
    guard let text = options["text"], !text.isEmpty else {
        failJSON("Missing non-empty --text argument", code: "missing_argument")
    }
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let wantSend = flags.contains("send")
    let silentMode = flags.contains("silent") || !wantSend
    if options["review-window"] != nil || options["review-title"] != nil ||
       flags.contains("review-window") || flags.contains("review-title") {
        guard !silentMode, let id = options["review-window"].flatMap(UInt32.init),
              let title = options["review-title"], !title.isEmpty else {
            failJSON("Invalid reviewed send target.", code: "review_target_changed")
        }
        cmdReviewedSend(text: text, expectedID: id, expectedTitle: title, kind: targetKind)
        return
    }

    let ensured = ensureAppMainWindow(kind: targetKind)
    guard let app = ensured.app else {
        failJSON("\(targetKind.appLabel) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }

    let windows = listWindows(for: targetKind)
    let hasWindowSelector = options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty
    let targetWin = selectTargetWindow(in: windows, options: options)
    if hasWindowSelector && targetWin == nil {
        failJSON(
            "No matching visible \(targetKind.appLabel) window found.",
            code: "window_not_found",
            extra: ["appId": targetKind.appId, "availableWindows": windows.map { $0.toDict() }]
        )
    }

    if let tw = targetWin, let twApp = NSRunningApplication(processIdentifier: tw.pid) {
        _ = twApp.unhide()
        _ = twApp.activate(options: [.activateIgnoringOtherApps])
    } else {
        _ = app.activate(options: [.activateIgnoringOtherApps])
    }
    usleep(200_000)

    let (frontOK, frontDesc) = isAppFrontmost(targetKind)
    guard frontOK else {
        failJSON("Aborted: frontmost app is '\(frontDesc)', expected \(targetKind.appLabel).", code: "not_frontmost", extra: ["appId": targetKind.appId])
    }

    // Save clipboard
    let pb = NSPasteboard.general
    let originalClipboard = pb.string(forType: .string)

    func restoreClipboard() {
        pb.clearContents()
        if let orig = originalClipboard {
            pb.setString(orig, forType: .string)
        }
    }

    // Focus input element via AX or geometry (supporting main or popup chat windows)
    let effectivePID = targetWin?.pid ?? app.processIdentifier
    var axInputEl: AXUIElement? = nil
    if let axWin = findAXWindow(pid: effectivePID, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]) {
        if hasWindowSelector {
            _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
            _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
            usleep(100_000)
        }
        axInputEl = findInputElement(in: axWin, windowBounds: targetWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) })
        if let el = axInputEl {
            _ = AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            if let pt = axPoint(el, kAXPositionAttribute), let sz = axSize(el, kAXSizeAttribute) {
                moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
            }
        }
    }
    if axInputEl == nil, let win = targetWin {
        moveAndClick(x: win.x + win.width * 0.60, y: win.y + win.height - 85.0)
    }
    usleep(180_000)

    let preExistingText = axInputEl.flatMap { axString($0, kAXValueAttribute) } ?? ""
    let cleanedStaleDraft = !preExistingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    let trimmedExpected = text.trimmingCharacters(in: .whitespacesAndNewlines)

    // Protect active human keyboard typing BEFORE touching the input box (never wipe user draft!)
    let entryHwKeyIdle = hardwareKeyboardIdleSeconds()
    if entryHwKeyIdle < 2.0 || (cleanedStaleDraft && entryHwKeyIdle < 12.0 && options["force-clear-draft"] != "1") {
        restoreClipboard()
        failJSON(
            "Human keyboard input detected; paused before touching input box to protect user typing.",
            code: "human_keyboard_active",
            extra: [
                "retryable": true,
                "hardwareKeyboardIdleSeconds": (entryHwKeyIdle * 100.0).rounded() / 100.0,
                "existingDraft": preExistingText,
            ]
        )
    }

    func performPasteAndReadback() -> (readback: String, source: String) {
        let (kbActive, kbIdle) = humanTypedSinceSyntheticKey(idleLimit: 1.0)
        if kbActive {
            restoreClipboard()
            failJSON(
                "Human keyboard activity detected right before paste; paused cleanly.",
                code: "human_keyboard_active",
                extra: ["retryable": true, "hardwareKeyboardIdleSeconds": kbIdle]
            )
        }
        if let el = axInputEl {
            _ = AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        }
        // Pre-clean: select all + delete any leftover / half-pasted text
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete, flags: [])
        usleep(80_000)

        // Paste text
        pb.clearContents()
        pb.setString(text, forType: .string)
        postKey(keyCode: kKeyV, flags: .maskCommand)
        usleep(250_000)

        var rb = ""
        var rbSrc = "ax"
        if let el = axInputEl, let axVal = axString(el, kAXValueAttribute) {
            rb = axVal
        } else {
            rbSrc = "clipboard"
            pb.clearContents()
            postKey(keyCode: kKeyA, flags: .maskCommand)
            usleep(80_000)
            postKey(keyCode: kKeyC, flags: .maskCommand)
            usleep(160_000)
            rb = pb.string(forType: .string) ?? ""
        }

        if rb.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           CGPreflightScreenCaptureAccess(),
           let win = targetWin,
           let image = captureWindowImage(win) {
            let imgW = Double(image.width)
            let imgH = Double(image.height)
            let scale = imgW / max(win.width, 1.0)
            let cropLeftFrac = win.isMainWindow ? 0.36 : 0.08
            let cropWidthFrac = win.isMainWindow ? 0.62 : 0.88
            let cropX = min(max(0.0, imgW * cropLeftFrac), max(0.0, imgW - 10.0))
            let cropY = max(0.0, imgH - 155.0 * scale)
            let cropW = min(imgW * cropWidthFrac, imgW - cropX)
            let cropH = min(115.0 * scale, imgH - cropY)
            if cropW > 10.0 && cropH > 10.0,
               let cropped = image.cropping(to: CGRect(x: cropX, y: cropY, width: cropW, height: cropH)),
               let results = try? runVisionOCR(cgImage: cropped) {
                let joined = results.compactMap { $0["text"] as? String }.joined(separator: " ")
                if !joined.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    rb = joined
                    rbSrc = "vision_ocr"
                }
            }
        }
        return (rb, rbSrc)
    }

    func matchesExpected(_ rb: String, source: String) -> Bool {
        if rb.contains(trimmedExpected) { return true }
        if source == "vision_ocr" {
            let stripWS: (String) -> String = { s in
                String(s.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) })
            }
            return stripWS(rb).contains(stripWS(trimmedExpected))
        }
        return false
    }

    var attempt = 1
    var (readback, readbackSource) = performPasteAndReadback()

    // 3x length dirty-input circuit breaker
    if readback.count > text.count * 3 {
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete)
        restoreClipboard()
        failJSON(
            "Dirty input circuit breaker triggered: readback length \(readback.count) > 3x expected \(text.count).",
            code: "dirty_input_circuit_breaker",
            extra: ["retryable": true, "expectedLen": text.count, "readbackLen": readback.count]
        )
    }

    // If interrupted mid-paste (partial/mismatched), clean input and retry once if window still frontmost
    if !matchesExpected(readback, source: readbackSource) {
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete)
        usleep(120_000)
        if isAppFrontmost(targetKind).0 {
            attempt = 2
            (readback, readbackSource) = performPasteAndReadback()
        }
        if !matchesExpected(readback, source: readbackSource) {
            postKey(keyCode: kKeyA, flags: .maskCommand)
            usleep(60_000)
            postKey(keyCode: kKeyDelete)
            restoreClipboard()
            failJSON(
                "Paste interrupted or readback mismatch; input box cleaned for safe retry.",
                code: "interrupted_during_paste",
                extra: [
                    "retryable": true,
                    "attempts": attempt,
                    "expected": text,
                    "readback": readback,
                    "readbackSource": readbackSource,
                ]
            )
        }
    }

    var sent = false
    if silentMode {
        // Clear input so nothing stays staged in silent verification mode
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete)
    } else {
        // Re-verify frontmost focus AND human keyboard idle right before pressing Return
        let (preReturnFront, preReturnDesc) = isAppFrontmost(targetKind)
        guard preReturnFront else {
            postKey(keyCode: kKeyA, flags: .maskCommand)
            usleep(60_000)
            postKey(keyCode: kKeyDelete)
            restoreClipboard()
            failJSON(
                "Window lost focus before Return (\(preReturnDesc)); aborted send and cleaned input for retry.",
                code: "interrupted_before_return",
                extra: ["retryable": true, "frontmost": preReturnDesc]
            )
        }
        let (preReturnTyping, preReturnHwKey) = humanTypedSinceSyntheticKey(idleLimit: 0.8)
        if preReturnTyping {
            postKey(keyCode: kKeyA, flags: .maskCommand)
            usleep(60_000)
            postKey(keyCode: kKeyDelete)
            restoreClipboard()
            failJSON(
                "Human started typing before Return; cleaned input and paused send for safe retry.",
                code: "human_keyboard_active",
                extra: ["retryable": true, "hardwareKeyboardIdleSeconds": preReturnHwKey]
            )
        }

        postKey(keyCode: kKeyRightArrow)
        usleep(60_000)
        postKey(keyCode: kKeyReturn)
        usleep(280_000)

        // Post-Return input-empty verification (handle IME candidate bar swallowing first Return)
        if let el = axInputEl, let remaining = axString(el, kAXValueAttribute), remaining.contains(trimmedExpected) {
            postKey(keyCode: kKeyRightArrow)
            usleep(60_000)
            postKey(keyCode: kKeyReturn)
            usleep(240_000)
            if let remaining2 = axString(el, kAXValueAttribute), remaining2.contains(trimmedExpected) {
                postKey(keyCode: kKeyA, flags: .maskCommand)
                usleep(60_000)
                postKey(keyCode: kKeyDelete)
                restoreClipboard()
                failJSON(
                    "Return keystroke did not dispatch message (text remained in input box); cleaned input for safe retry.",
                    code: "return_not_dispatched",
                    extra: ["retryable": true, "readback": remaining2]
                )
            }
        }
        sent = true
    }

    restoreClipboard()
    var resp: [String: Any] = [
        "ok": true,
        "appId": targetKind.appId,
        "appLabel": targetKind.appLabel,
        "verified": true,
        "sent": sent,
        "silentMode": silentMode,
        "attempts": attempt,
        "cleanedStaleDraft": cleanedStaleDraft,
        "readbackLength": readback.count,
        "readbackSource": readbackSource,
    ]
    if let win = targetWin {
        resp["windowID"] = win.windowID
        resp["windowTitle"] = win.title
    }
    writeJSON(resp)
}

func cmdSendSticker(flags: Set<String>, options: [String: String]) {
    guard AXIsProcessTrusted() else {
        failJSON("Accessibility permission (AXIsProcessTrusted) is not granted.", code: "ax_permission_denied")
    }
    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let ensured = ensureAppMainWindow(kind: targetKind)
    guard let app = ensured.app else {
        failJSON("\(targetKind.appLabel) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }

    let windows = listWindows(for: targetKind)
    let hasWindowSelector = options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty
    guard let targetWin = selectTargetWindow(in: windows, options: options) else {
        failJSON(
            "No matching visible \(targetKind.appLabel) window found.",
            code: hasWindowSelector ? "window_not_found" : "no_window",
            extra: ["appId": targetKind.appId]
        )
    }

    let tab = (options["tab"] ?? "favorites").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let slot = max(0, min(24, Int(options["slot"] ?? "0") ?? 0))
    let dryRun = flags.contains("dry-run") || options["dry-run"] == "1"

    let leftPaneOffset: Double = {
        if let rawSplit = options["split-x"], let parsed = Double(rawSplit), parsed > 0 {
            return parsed
        }
        return targetWin.isMainWindow ? max(218.0, min(320.0, targetWin.width * 0.36)) : 0.0
    }()

    let emojiBtnX = targetWin.x + leftPaneOffset + 25.0
    let emojiBtnY = targetWin.y + targetWin.height - 29.0
    let tabX = targetWin.x + leftPaneOffset + (tab == "emoji" ? 68.0 : 102.0)
    let tabY = targetWin.y + targetWin.height - 78.0

    let slotX: Double
    let slotY: Double
    if tab == "emoji" {
        let col = slot % 8
        let row = slot / 8
        slotX = targetWin.x + leftPaneOffset + 38.0 + Double(col) * 38.0
        slotY = targetWin.y + targetWin.height - 355.0 + Double(row) * 38.0
    } else {
        let col = slot % 5
        let row = slot / 5
        slotX = targetWin.x + leftPaneOffset + 50.0 + Double(col) * 68.0
        slotY = targetWin.y + targetWin.height - 375.0 + Double(row) * 68.0
    }

    if dryRun {
        writeJSON([
            "ok": true,
            "sent": false,
            "dryRun": true,
            "tab": tab,
            "slot": slot,
            "windowID": targetWin.windowID,
            "windowTitle": targetWin.title,
            "emojiButton": ["x": emojiBtnX, "y": emojiBtnY],
            "tabButton": ["x": tabX, "y": tabY],
            "slotPoint": ["x": slotX, "y": slotY],
        ])
        return
    }

    if let twApp = NSRunningApplication(processIdentifier: targetWin.pid) {
        _ = twApp.unhide()
        _ = twApp.activate(options: [.activateIgnoringOtherApps])
    } else {
        _ = app.activate(options: [.activateIgnoringOtherApps])
    }
    if let axWin = findAXWindow(pid: targetWin.pid, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]) {
        _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
    }
    usleep(220_000)

    let (frontOK, frontDesc) = isAppFrontmost(targetKind)
    guard frontOK else {
        failJSON("Aborted: frontmost app is '\(frontDesc)', expected \(targetKind.appLabel).", code: "not_frontmost", extra: ["appId": targetKind.appId])
    }

    // 1) Open emoji/sticker popover
    moveAndClick(x: emojiBtnX, y: emojiBtnY)
    usleep(280_000)
    // 2) Switch to requested tab (favorites ❤️ or default emoji 😊)
    moveAndClick(x: tabX, y: tabY)
    usleep(240_000)
    // 3) Click target sticker / emoji cell
    moveAndClick(x: slotX, y: slotY)
    usleep(180_000)
    // For emoji text cells, confirm sending with Return (favorite stickers send directly on click)
    if tab == "emoji" {
        postKey(keyCode: kKeyReturn)
        usleep(220_000)
    }

    writeJSON([
        "ok": true,
        "sent": true,
        "tab": tab,
        "slot": slot,
        "windowID": targetWin.windowID,
        "windowTitle": targetWin.title,
        "slotPoint": ["x": slotX, "y": slotY],
    ])
}

func cmdPasteImage(flags: Set<String>, options: [String: String]) {
    guard let imgPath = options["image"], !imgPath.isEmpty else {
        failJSON("Missing non-empty --image <path> argument", code: "missing_argument")
    }
    var isDir: ObjCBool = false
    guard FileManager.default.fileExists(atPath: imgPath, isDirectory: &isDir), !isDir.boolValue else {
        failJSON("Image file not found: \(imgPath)", code: "file_not_found")
    }
    guard let nsImage = NSImage(contentsOfFile: imgPath),
          let tiff = nsImage.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let pngData = rep.representation(using: .png, properties: [:]) else {
        failJSON("Unable to decode image file: \(imgPath)", code: "invalid_image")
    }

    let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
    let wantSend = flags.contains("send")
    let silentMode = flags.contains("silent") || !wantSend
    let dryRun = flags.contains("dry-run") || options["dry-run"] == "1"

    let windows = listWindows(for: targetKind)
    let hasWindowSelector = options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty
    let targetWin = selectTargetWindow(in: windows, options: options)
    if dryRun {
        writeJSON([
            "ok": true,
            "sent": false,
            "dryRun": true,
            "imagePath": imgPath,
            "pngBytes": pngData.count,
            "imageWidth": rep.pixelsWide,
            "imageHeight": rep.pixelsHigh,
            "windowID": targetWin?.windowID as Any,
            "windowTitle": targetWin?.title as Any,
        ])
        return
    }

    guard hardwareKeyboardIdleSeconds() >= 1.5 else {
        failJSON(
            "Human keyboard activity detected; paused image paste cleanly.",
            code: "human_keyboard_active",
            extra: ["retryable": true]
        )
    }

    let ensured = ensureAppMainWindow(kind: targetKind)
    guard let app = ensured.app else {
        failJSON("\(targetKind.appLabel) is not running.", code: targetKind.notRunningErrorCode, extra: ["appId": targetKind.appId])
    }
    if hasWindowSelector && targetWin == nil {
        failJSON("No matching visible \(targetKind.appLabel) window found.", code: "window_not_found")
    }

    if let tw = targetWin, let twApp = NSRunningApplication(processIdentifier: tw.pid) {
        _ = twApp.unhide()
        _ = twApp.activate(options: [.activateIgnoringOtherApps])
    } else {
        _ = app.activate(options: [.activateIgnoringOtherApps])
    }
    usleep(220_000)

    let (frontOK, frontDesc) = isAppFrontmost(targetKind)
    guard frontOK else {
        failJSON("Aborted: frontmost app is '\(frontDesc)', expected \(targetKind.appLabel).", code: "not_frontmost")
    }

    let pb = NSPasteboard.general
    let originalClipboard = pb.string(forType: .string)
    func restoreClipboard() {
        pb.clearContents()
        if let orig = originalClipboard {
            pb.setString(orig, forType: .string)
        }
    }

    let effectivePID = targetWin?.pid ?? app.processIdentifier
    var focusedInput = false
    if let axWin = findAXWindow(pid: effectivePID, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]),
       let inputEl = findInputElement(in: axWin) {
        _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
        _ = AXUIElementSetAttributeValue(inputEl, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        if let pt = axPoint(inputEl, kAXPositionAttribute), let sz = axSize(inputEl, kAXSizeAttribute) {
            moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
            focusedInput = true
        }
    }
    if !focusedInput, let win = targetWin {
        moveAndClick(x: win.x + win.width * 0.60, y: win.y + win.height - 85.0)
    }
    usleep(180_000)

    pb.clearContents()
    pb.declareTypes([.png, .tiff], owner: nil)
    pb.setData(pngData, forType: .png)
    pb.setData(tiff, forType: .tiff)
    postKey(keyCode: kKeyV, flags: .maskCommand)
    usleep(380_000)

    var sent = false
    if !silentMode {
        let (kbTyping, kbIdle) = humanTypedSinceSyntheticKey(idleLimit: 0.8)
        guard isAppFrontmost(targetKind).0, !kbTyping else {
            restoreClipboard()
            failJSON("Interrupted before sending image; aborted cleanly.", code: "interrupted_before_return", extra: ["retryable": true, "hardwareKeyboardIdleSeconds": kbIdle])
        }
        postKey(keyCode: kKeyReturn)
        usleep(320_000)
        sent = true
    }

    restoreClipboard()
    writeJSON([
        "ok": true,
        "sent": sent,
        "silentMode": silentMode,
        "imagePath": imgPath,
        "pngBytes": pngData.count,
        "windowID": targetWin?.windowID as Any,
        "windowTitle": targetWin?.title as Any,
    ])
}

func cmdAnnotateImage(options: [String: String]) {
    guard let imgPath = options["image"], !imgPath.isEmpty else {
        failJSON("Missing --image <src_path>", code: "missing_argument")
    }
    guard let outPath = options["out"], !outPath.isEmpty else {
        failJSON("Missing --out <dst_path>", code: "missing_argument")
    }
    guard let cgImage = loadCGImage(at: imgPath) else {
        failJSON("Unable to load image: \(imgPath)", code: "file_not_found")
    }

    let imgW = cgImage.width
    let imgH = cgImage.height
    let keywords = (options["keywords"] ?? "")
        .split(separator: ",")
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        .filter { !$0.isEmpty }
    let noteText = (options["note"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)

    struct AnnotBox {
        let x: Int
        let y: Int
        let width: Int
        let height: Int
        let label: String
    }

    var targetBoxes: [AnnotBox] = []
    if let rawBoxes = options["boxes"], !rawBoxes.isEmpty {
        for part in rawBoxes.split(separator: ";") {
            let nums = part.split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            if nums.count == 4 && nums[2] > 4 && nums[3] > 4 {
                targetBoxes.append(AnnotBox(x: nums[0], y: nums[1], width: nums[2], height: nums[3], label: ""))
            }
        }
    }

    let ocrItems = (try? runVisionOCR(cgImage: cgImage)) ?? []
    if targetBoxes.isEmpty && !keywords.isEmpty {
        for item in ocrItems {
            let txt = (item["text"] as? String) ?? ""
            let lower = txt.lowercased()
            if keywords.contains(where: { lower.contains($0) }),
               let b = item["bbox"] as? [String: Int],
               let bx = b["x"], let by = b["y"], let bw = b["width"], let bh = b["height"] {
                targetBoxes.append(AnnotBox(x: bx, y: by, width: bw, height: bh, label: txt))
                if targetBoxes.count >= 4 { break }
            }
        }
    }
    if targetBoxes.isEmpty {
        // Fallback: highlight top 2 prominent OCR regions (excluding tiny noise)
        let informative = ocrItems.filter { (($0["text"] as? String) ?? "").count >= 4 }
        for item in informative.prefix(2) {
            if let b = item["bbox"] as? [String: Int],
               let bx = b["x"], let by = b["y"], let bw = b["width"], let bh = b["height"] {
                targetBoxes.append(AnnotBox(x: bx, y: by, width: bw, height: bh, label: (item["text"] as? String) ?? ""))
            }
        }
    }
    if targetBoxes.isEmpty {
        // Pure photo without OCR text -> center focal box
        targetBoxes.append(AnnotBox(
            x: Int(Double(imgW) * 0.18),
            y: Int(Double(imgH) * 0.18),
            width: max(24, Int(Double(imgW) * 0.64)),
            height: max(24, Int(Double(imgH) * 0.56)),
            label: "重点区域"
        ))
    }

    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: imgW,
        pixelsHigh: imgH,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        failJSON("Failed to allocate annotation bitmap.", code: "bitmap_alloc_failed")
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    // Draw base image cleanly in Cocoa bottom-left coordinate space
    let srcNS = NSImage(cgImage: cgImage, size: NSSize(width: imgW, height: imgH))
    srcNS.draw(in: NSRect(x: 0, y: 0, width: imgW, height: imgH))

    let strokeWidth = max(3.0, min(6.0, CGFloat(imgW) / 240.0))
    let redStroke = NSColor(calibratedRed: 0.98, green: 0.32, blue: 0.32, alpha: 0.96)
    let redFill = NSColor(calibratedRed: 0.98, green: 0.32, blue: 0.32, alpha: 0.10)

    var outBoxesMeta: [[String: Any]] = []
    for (idx, box) in targetBoxes.enumerated() {
        let pad = 6
        let px = max(2, box.x - pad)
        let pyTop = max(2, box.y - pad)
        let pw = min(imgW - px - 2, box.width + pad * 2)
        let ph = min(imgH - pyTop - 2, box.height + pad * 2)
        // Flip top-left Vision pixel y -> bottom-left Cocoa y
        let drawY = CGFloat(imgH - pyTop - ph)
        let rect = NSRect(x: CGFloat(px), y: drawY, width: CGFloat(max(8, pw)), height: CGFloat(max(8, ph)))

        let rounded = NSBezierPath(roundedRect: rect, xRadius: 6.0, yRadius: 6.0)
        redFill.setFill()
        rounded.fill()
        redStroke.setStroke()
        rounded.lineWidth = strokeWidth
        rounded.stroke()

        // Numbered red badge (1, 2, 3...) near top-left corner of box
        let badgeSize = max(20.0, min(28.0, CGFloat(imgW) / 30.0))
        let badgeRect = NSRect(
            x: max(4.0, rect.minX - badgeSize * 0.35),
            y: min(CGFloat(imgH) - badgeSize - 4.0, rect.maxY - badgeSize * 0.5),
            width: badgeSize,
            height: badgeSize
        )
        let circle = NSBezierPath(ovalIn: badgeRect)
        redStroke.setFill()
        circle.fill()
        let numAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: badgeSize * 0.58, weight: .bold),
            .foregroundColor: NSColor.white,
        ]
        let numStr = NSAttributedString(string: "\(idx + 1)", attributes: numAttrs)
        let numSz = numStr.size()
        numStr.draw(at: NSPoint(x: badgeRect.midX - numSz.width / 2.0, y: badgeRect.midY - numSz.height / 2.0))

        outBoxesMeta.append([
            "index": idx + 1,
            "x": px,
            "y": pyTop,
            "width": pw,
            "height": ph,
            "label": box.label,
        ])
    }

    if !noteText.isEmpty {
        let fontSize = max(14.0, min(22.0, CGFloat(imgW) / 36.0))
        let noteAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize, weight: .semibold),
            .foregroundColor: NSColor.white,
        ]
        let displayNote = "标注说明：\(noteText)"
        let textSz = NSAttributedString(string: displayNote, attributes: noteAttrs).size()
        let barH = min(CGFloat(imgH) * 0.22, textSz.height + 18.0)
        let barW = min(CGFloat(imgW) - 24.0, textSz.width + 28.0)
        let barRect = NSRect(x: 12.0, y: 12.0, width: barW, height: barH)
        let barPath = NSBezierPath(roundedRect: barRect, xRadius: 8.0, yRadius: 8.0)
        NSColor(calibratedWhite: 0.08, alpha: 0.84).setFill()
        barPath.fill()
        NSAttributedString(string: displayNote, attributes: noteAttrs).draw(
            in: NSRect(x: barRect.minX + 14.0, y: barRect.minY + 7.0, width: barRect.width - 28.0, height: barRect.height - 14.0)
        )
    }

    NSGraphicsContext.restoreGraphicsState()

    guard let pngData = rep.representation(using: .png, properties: [:]) else {
        failJSON("Failed to encode annotated PNG.", code: "png_encode_failed")
    }
    do {
        let dstUrl = URL(fileURLWithPath: outPath)
        try FileManager.default.createDirectory(at: dstUrl.deletingLastPathComponent(), withIntermediateDirectories: true)
        try pngData.write(to: dstUrl)
        writeJSON([
            "ok": true,
            "srcPath": imgPath,
            "outPath": outPath,
            "imageWidth": imgW,
            "imageHeight": imgH,
            "annotatedCount": outBoxesMeta.count,
            "matchedBoxes": outBoxesMeta,
            "note": noteText,
        ])
    } catch {
        failJSON("Failed to write annotated PNG: \(error.localizedDescription)", code: "write_failed")
    }
}

func renderPDFPageToCGImage(_ page: PDFPage, maxDimension: CGFloat = 2200.0, scale: CGFloat = 2.0) -> CGImage? {
    let cropBox = page.bounds(for: .cropBox)
    guard cropBox.width > 1, cropBox.height > 1 else { return nil }
    let rotation = ((page.rotation % 360) + 360) % 360
    let displayWidth = (rotation == 90 || rotation == 270) ? cropBox.height : cropBox.width
    let displayHeight = (rotation == 90 || rotation == 270) ? cropBox.width : cropBox.height
    guard displayWidth > 1, displayHeight > 1 else { return nil }

    let clampedScale = max(1.0, min(scale, maxDimension / max(displayWidth, displayHeight)))
    let pixelW = max(1, Int((displayWidth * clampedScale).rounded()))
    let pixelH = max(1, Int((displayHeight * clampedScale).rounded()))

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(
        data: nil,
        width: pixelW,
        height: pixelH,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return nil
    }
    ctx.setFillColor(NSColor.white.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: pixelW, height: pixelH))
    ctx.saveGState()
    ctx.scaleBy(x: clampedScale, y: clampedScale)
    // PDFPage.draw(with:to:) applies the page's cropBox/rotation transform internally.
    page.draw(with: .cropBox, to: ctx)
    ctx.restoreGState()
    return ctx.makeImage()
}

func cmdExtractPDFText(options: [String: String]) {
    guard let pdfPath = options["pdf"], !pdfPath.isEmpty else {
        failJSON("Missing --pdf <path>", code: "missing_argument")
    }
    var isDir: ObjCBool = false
    guard FileManager.default.fileExists(atPath: pdfPath, isDirectory: &isDir), !isDir.boolValue else {
        failJSON("PDF file not found: \(pdfPath)", code: "file_not_found")
    }
    let pdfURL = URL(fileURLWithPath: pdfPath)
    guard let doc = PDFDocument(url: pdfURL) else {
        failJSON("Unable to open PDF document: \(pdfPath)", code: "invalid_pdf")
    }
    if doc.isLocked && !doc.unlock(withPassword: "") {
        failJSON("PDF document is encrypted/locked: \(pdfPath)", code: "pdf_locked")
    }

    let pageCount = doc.pageCount
    let maxPages: Int
    if let rawMax = options["max-pages"] {
        guard let parsedMax = Int(rawMax), parsedMax > 0 else {
            failJSON("Invalid --max-pages value '\(rawMax)'. Must be a positive integer.", code: "invalid_argument")
        }
        maxPages = parsedMax
    } else {
        maxPages = pageCount
    }

    let langsRaw = options["langs"] ?? "zh-Hans,en-US"
    let langs = langsRaw.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }

    let pagesToProcess = min(pageCount, maxPages)
    var pagesOut: [[String: Any]] = []
    var nonEmptyTexts: [String] = []
    let minDirectCharsForNoOCR = 20

    for idx in 0..<pagesToProcess {
        guard let page = doc.page(at: idx) else { continue }
        let pdfText = (page.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let pdfCompactCount = pdfText.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) }.count

        var pageSource = "pdfkit"
        var finalText = pdfText

        if pdfCompactCount < minDirectCharsForNoOCR,
           let cgImg = renderPDFPageToCGImage(page),
           let ocrItems = try? runVisionOCR(cgImage: cgImg, languages: langs) {
            let ocrText = ocrItems.compactMap { $0["text"] as? String }
                .joined(separator: "\n")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let ocrCompactCount = ocrText.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) }.count
            if !ocrText.isEmpty && (pdfCompactCount == 0 || ocrCompactCount > pdfCompactCount) {
                pageSource = "ocr"
                finalText = ocrText
            }
        }

        pagesOut.append([
            "page": idx + 1,
            "source": pageSource,
            "text": finalText,
        ])
        if !finalText.isEmpty {
            nonEmptyTexts.append(finalText)
        }
    }

    writeJSON([
        "ok": true,
        "pdfPath": pdfPath,
        "pageCount": pageCount,
        "processedPages": pagesOut.count,
        "truncated": pagesOut.count < pageCount,
        "text": nonEmptyTexts.joined(separator: "\n\n"),
        "pages": pagesOut,
    ])
}

let kKeyEscape: CGKeyCode = 53

func findTencentMeetingWindows(includeFloating: Bool = false) -> [(wid: UInt32, pid: pid_t, x: Double, y: Double, w: Double, h: Double, title: String)] {
    var out: [(UInt32, pid_t, Double, Double, Double, Double, String)] = []
    for entry in copyOnScreenWindowInfo() {
        let owner = (entry[kCGWindowOwnerName as String] as? String) ?? ""
        let layer = (entry[kCGWindowLayer as String] as? Int) ?? 0
        guard (layer == 0 || includeFloating), owner.contains("腾讯会议") || owner.lowercased().contains("tencentmeeting") else { continue }
        guard let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              w > 80, h > 80,
              let wid = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
              let pid = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value else { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let title = (entry[kCGWindowName as String] as? String) ?? ""
        out.append((wid, pid, x, y, w, h, title))
    }
    return out
}

func ocrTMWindowByID(_ wid: UInt32, winX: Double, winY: Double, winW: Double, winH: Double) -> ([[String: Any]], Double, Double)? {
    guard let img = CGWindowListCreateImage(.null, .optionIncludingWindow, wid, [.boundsIgnoreFraming, .bestResolution]),
          let elems = try? runVisionOCR(cgImage: img) else {
        return nil
    }
    let sx = Double(img.width) / max(1.0, winW)
    let sy = Double(img.height) / max(1.0, winH)
    return (elems, sx, sy)
}

func findTMOCRPoint(_ elems: [[String: Any]], sx: Double, sy: Double, winX: Double, winY: Double, matching keywords: [String], minRelY: Double = 0.0) -> (x: Double, y: Double, relY: Double, text: String)? {
    for kw in keywords {
        for item in elems {
            let t = (item["text"] as? String) ?? ""
            if t.contains(kw), let pt = item["center"] as? [String: Int], let cx = pt["x"], let cy = pt["y"] {
                let relY = Double(cy) / sy
                if relY >= minRelY {
                    return (winX + Double(cx) / sx, winY + relY, relY, t)
                }
            }
        }
    }
    return nil
}

func ensureTencentMeetingSubtitlesAndYuanbao(wantSubtitles: Bool = true, wantYuanbao: Bool = true) -> [String: Any] {
    let tmRunning = NSWorkspace.shared.runningApplications.first(where: { ($0.bundleIdentifier ?? "") == "com.tencent.meeting" })
    let floatingWins = findTencentMeetingWindows(includeFloating: true)
    let tmPid: pid_t? = floatingWins.first?.pid ?? tmRunning?.processIdentifier

    if let pid = tmPid {
        if let tmApp = NSRunningApplication(processIdentifier: pid) {
            _ = tmApp.unhide()
            _ = tmApp.activate(options: [.activateIgnoringOtherApps])
        }
        let preAxApp = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(preAxApp, 0.35)
        var winListRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(preAxApp, kAXWindowsAttribute as CFString, &winListRef) == .success,
           let axWins = winListRef as? [AXUIElement] {
            for axw in axWins {
                AXUIElementSetMessagingTimeout(axw, 0.35)
                var minRef: CFTypeRef?
                if AXUIElementCopyAttributeValue(axw, kAXMinimizedAttribute as CFString, &minRef) == .success,
                   (minRef as? Bool) == true {
                    _ = AXUIElementSetAttributeValue(axw, kAXMinimizedAttribute as CFString, kCFBooleanFalse)
                    usleep(200_000)
                }
            }
        }
    }

    var wins = findTencentMeetingWindows(includeFloating: false)
    if wins.first(where: { $0.w > 800 && $0.h > 480 }) == nil {
        // Restore from floating PiP window (w ~ 140..450, h ~ 90..320, excluding 720x480 home window)
        if let pip = findTencentMeetingWindows(includeFloating: true).first(where: {
            $0.w >= 140 && $0.w <= 450 && $0.h >= 90 && $0.h <= 320 && !($0.w == 720 && $0.h == 480)
        }) {
            let cx = pip.x + pip.w * 0.5
            let cy = pip.y + pip.h * 0.45
            let pt = CGPoint(x: cx, y: cy)
            CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
            usleep(120_000)
            for clickIdx in 1...2 {
                if let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left),
                   let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left) {
                    down.setIntegerValueField(.mouseEventClickState, value: Int64(clickIdx))
                    up.setIntegerValueField(.mouseEventClickState, value: Int64(clickIdx))
                    down.post(tap: .cghidEventTap)
                    usleep(45_000)
                    up.post(tap: .cghidEventTap)
                    usleep(65_000)
                }
            }
            usleep(850_000)
            wins = findTencentMeetingWindows(includeFloating: false)
        }
    }

    guard let mainMeeting = wins.first(where: { $0.w > 800 && $0.h > 480 }) else {
        return ["ok": false, "error": "no_active_meeting_window", "yuanbaoEnabled": false, "subtitlesEnabled": false]
    }
    if let tmApp = NSRunningApplication(processIdentifier: mainMeeting.pid) {
        _ = tmApp.unhide()
        _ = tmApp.activate(options: [.activateIgnoringOtherApps])
    }
    let axApp = AXUIElementCreateApplication(mainMeeting.pid)
    AXUIElementSetMessagingTimeout(axApp, 0.35)
    var mainAxListRef: CFTypeRef?
    if AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &mainAxListRef) == .success,
       let axWins = mainAxListRef as? [AXUIElement] {
        for axw in axWins {
            AXUIElementSetMessagingTimeout(axw, 0.35)
            if let sz = axSize(axw, kAXSizeAttribute), abs(Double(sz.width) - mainMeeting.w) <= 8.0 && abs(Double(sz.height) - mainMeeting.h) <= 8.0 {
                _ = AXUIElementSetAttributeValue(axw, kAXMainAttribute as CFString, kCFBooleanTrue)
                _ = AXUIElementPerformAction(axw, kAXRaiseAction as CFString)
                break
            }
        }
    }
    usleep(260_000)

    // Unmute microphone if currently muted
    var micState = "unknown"
    var q: [AXUIElement] = [axApp]
    var qi = 0
    while qi < q.count && qi < 80 {
        let el = q[qi]; qi += 1
        AXUIElementSetMessagingTimeout(el, 0.25)
        if axString(el, kAXTitleAttribute) == "mic_button" {
            let d = axString(el, kAXDescriptionAttribute) ?? ""
            micState = d
            if d.contains("解除静音") {
                _ = AXUIElementPerformAction(el, kAXPressAction as CFString)
                micState = "unmuted_now"
                usleep(180_000)
            }
            break
        }
        q.append(contentsOf: axChildren(el))
    }

    // Wake bottom toolbar in case auto-hidden
    if let moveEv = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: CGPoint(x: mainMeeting.x + mainMeeting.w * 0.45, y: mainMeeting.y + mainMeeting.h - 28.0), mouseButton: .left) {
        moveEv.post(tap: .cghidEventTap)
    }
    usleep(450_000)

    var yuanbaoEnabled = false
    var subtitlesEnabled = false

    if wantYuanbao, let (elems, sx, sy) = ocrTMWindowByID(mainMeeting.wid, winX: mainMeeting.x, winY: mainMeeting.y, winW: mainMeeting.w, winH: mainMeeting.h) {
        let fullTxt = elems.compactMap { $0["text"] as? String }.joined(separator: " ")
        if fullTxt.contains("元宝会议助手") || fullTxt.contains("会议概览") || fullTxt.contains("持续总结") || fullTxt.contains("洞察讨论观点") {
            yuanbaoEnabled = true
        } else if let yb = findTMOCRPoint(elems, sx: sx, sy: sy, winX: mainMeeting.x, winY: mainMeeting.y, matching: ["元宝笔记"], minRelY: mainMeeting.h * 0.82) {
            moveAndClick(x: yb.x, y: yb.y - 12.0)
            usleep(750_000)
            yuanbaoEnabled = true
        }
    }

    if wantSubtitles, let (elems2, sx2, sy2) = ocrTMWindowByID(mainMeeting.wid, winX: mainMeeting.x, winY: mainMeeting.y, winW: mainMeeting.w, winH: mainMeeting.h) {
        let fullTxt2 = elems2.compactMap { $0["text"] as? String }.joined(separator: " ")
        if fullTxt2.contains("关闭字幕") || fullTxt2.contains("关闭宇幕") {
            subtitlesEnabled = true
        } else {
            var appClickPt: (Double, Double)? = nil
            if let appBtn = findTMOCRPoint(elems2, sx: sx2, sy: sy2, winX: mainMeeting.x, winY: mainMeeting.y, matching: ["应用"], minRelY: mainMeeting.h * 0.82) {
                appClickPt = (appBtn.x, appBtn.y - 12.0)
            } else if let yb = findTMOCRPoint(elems2, sx: sx2, sy: sy2, winX: mainMeeting.x, winY: mainMeeting.y, matching: ["元宝笔记"], minRelY: mainMeeting.h * 0.82) {
                // "应用" toolbar button sits reliably 64pt to the right of "元宝笔记" even when a red badge hides OCR text
                appClickPt = (yb.x + 64.0, yb.y - 12.0)
            }
            if let pt = appClickPt {
                moveAndClick(x: pt.0, y: pt.1)
                usleep(650_000)
                let popWins = findTencentMeetingWindows(includeFloating: true).filter { $0.wid != mainMeeting.wid && $0.w < 900 && $0.h < 800 }
                var handled = false
                for pw in popWins {
                    guard let (pe, psx, psy) = ocrTMWindowByID(pw.wid, winX: pw.x, winY: pw.y, winW: pw.w, winH: pw.h) else { continue }
                    if findTMOCRPoint(pe, sx: psx, sy: psy, winX: pw.x, winY: pw.y, matching: ["关闭字幕", "关闭宇幕"]) != nil {
                        subtitlesEnabled = true
                        handled = true
                        postKey(keyCode: kKeyEscape)
                        usleep(220_000)
                        break
                    }
                    if let openSub = findTMOCRPoint(pe, sx: psx, sy: psy, winX: pw.x, winY: pw.y, matching: ["开启字幕", "开启宇幕"]) {
                        moveAndClick(x: openSub.x, y: openSub.y - 12.0)
                        usleep(500_000)
                        subtitlesEnabled = true
                        handled = true
                        break
                    }
                }
                if !handled {
                    postKey(keyCode: kKeyEscape)
                    usleep(180_000)
                }
            }
        }
    }

    return [
        "ok": true,
        "windowID": mainMeeting.wid,
        "yuanbaoEnabled": yuanbaoEnabled,
        "subtitlesEnabled": subtitlesEnabled,
        "micState": micState,
    ]
}

func cmdSetupTencentMeeting(flags: Set<String>, options: [String: String]) {
    let res = ensureTencentMeetingSubtitlesAndYuanbao(
        wantSubtitles: options["subtitles"] != "0",
        wantYuanbao: options["yuanbao"] != "0"
    )
    writeJSON(res)
}

func cmdJoinTencentMeeting(flags: Set<String>, options: [String: String]) {
    let dryRun = flags.contains("dry-run") || options["dry-run"] == "1"
    let wantClickCard = flags.contains("click-card") || options["click-card"] == "1"
    var meetingCode = (options["meeting-code"] ?? "").filter { $0.isNumber }
    let password = (options["password"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)

    func extractDigitsCode(_ raw: String) -> String {
        if let regex = try? NSRegularExpression(pattern: "(?<!\\d)(\\d[\\s\\-]?){9,11}(?!\\d)") {
            let ns = raw as NSString
            if let m = regex.firstMatch(in: raw, range: NSRange(location: 0, length: ns.length)) {
                let digits = ns.substring(with: m.range).filter { $0.isNumber }
                if (9...11).contains(digits.count) {
                    return digits
                }
            }
        }
        return ""
    }

    func findLocalTMWindows() -> [(wid: UInt32, pid: pid_t, x: Double, y: Double, w: Double, h: Double, title: String)] {
        return findTencentMeetingWindows(includeFloating: false)
    }

    func ocrWindowByID(_ wid: UInt32, winX: Double, winY: Double, winW: Double, winH: Double) -> ([[String: Any]], Double, Double)? {
        return ocrTMWindowByID(wid, winX: winX, winY: winY, winW: winW, winH: winH)
    }

    func findOCRPoint(_ elems: [[String: Any]], sx: Double, sy: Double, winX: Double, winY: Double, matching keywords: [String]) -> (x: Double, y: Double, text: String)? {
        return findTMOCRPoint(elems, sx: sx, sy: sy, winX: winX, winY: winY, matching: keywords).map { ($0.x, $0.y, $0.text) }
    }

    // Check if password prompt or active meeting window is already present
    func scanTMState() -> (needsPwd: Bool, pwdWin: (wid: UInt32, pid: pid_t, x: Double, y: Double, w: Double, h: Double, title: String)?, pwdFieldPt: (Double, Double)?, joinBtnPt: (Double, Double)?, inMeeting: Bool) {
        let wins = findTencentMeetingWindows()
        for w in wins {
            guard let (elems, sx, sy) = ocrWindowByID(w.wid, winX: w.x, winY: w.y, winW: w.w, winH: w.h) else { continue }
            let joinedText = elems.compactMap { $0["text"] as? String }.joined(separator: " ")
            if joinedText.contains("入会密码") || joinedText.contains("请输入会议密码") {
                let fieldPt = findOCRPoint(elems, sx: sx, sy: sy, winX: w.x, winY: w.y, matching: ["请输入会议密码"])
                    .map { ($0.x, $0.y) } ?? (w.x + w.w * 0.5, w.y + w.h * 0.376)
                let btnPt = findOCRPoint(elems, sx: sx, sy: sy, winX: w.x, winY: w.y, matching: ["进入会议", "加入会议"])
                    .map { ($0.x, $0.y) } ?? (w.x + w.w * 0.80, w.y + w.h * 0.89)
                return (true, w, fieldPt, btnPt, false)
            }
            if joinedText.contains("结束会议") || joinedText.contains("离开会议") || joinedText.contains("会议详情") || joinedText.contains("解除静音") || joinedText.contains("静音") || (joinedText.contains("邀请") && joinedText.contains("成员")) {
                return (false, nil, nil, nil, true)
            }
        }
        return (false, nil, nil, nil, false)
    }

    if dryRun {
        let tmState = scanTMState()
        writeJSON([
            "ok": true,
            "dryRun": true,
            "meetingCode": meetingCode,
            "needsPassword": tmState.needsPwd,
            "inMeeting": tmState.inMeeting,
        ])
        return
    }

    var clickedCardPt: [String: Double]? = nil
    var clickedMiniProgramJoin = false
    var state = scanTMState()

    if !state.needsPwd && !state.inMeeting && (wantClickCard || options["window-id"] != nil || !(options["window-title"] ?? "").isEmpty) {
        let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
        let windows = listWindows(for: targetKind)
        if let targetWin = selectTargetWindow(in: windows, options: options),
           let (elems, sx, sy) = ocrWindowByID(targetWin.windowID, winX: targetWin.x, winY: targetWin.y, winW: targetWin.width, winH: targetWin.height) {
            if meetingCode.isEmpty {
                meetingCode = extractDigitsCode(elems.compactMap { $0["text"] as? String }.joined(separator: " "))
            }
            if let hit = findOCRPoint(elems, sx: sx, sy: sy, winX: targetWin.x, winY: targetWin.y, matching: ["会议已经开始", "个人会议室", "会议号", "腾讯会议"]) {
                if let wxApp = NSRunningApplication(processIdentifier: targetWin.pid) {
                    _ = wxApp.unhide()
                    _ = wxApp.activate(options: [.activateIgnoringOtherApps])
                }
                if let axWin = findAXWindow(pid: targetWin.pid, kind: targetKind, targetWin: targetWin, reqTitle: options["window-title"]) {
                    _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
                    _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
                }
                usleep(220_000)
                moveAndClick(x: hit.x, y: hit.y)
                clickedCardPt = ["x": hit.x, "y": hit.y]
                usleep(1_400_000)

                // Check if WeChat Mini Program ("微信 (窗口)") popped up with a blue "加入会议" button
                let updatedWins = listWindows(for: targetKind)
                if let miniWin = updatedWins.first(where: { $0.title.contains("微信") && $0.windowID != targetWin.windowID }),
                   let (mElems, msx, msy) = ocrWindowByID(miniWin.windowID, winX: miniWin.x, winY: miniWin.y, winW: miniWin.width, winH: miniWin.height),
                   let joinHit = findOCRPoint(mElems, sx: msx, sy: msy, winX: miniWin.x, winY: miniWin.y, matching: ["加入会议"]) {
                    if meetingCode.isEmpty {
                        meetingCode = extractDigitsCode(mElems.compactMap { $0["text"] as? String }.joined(separator: " "))
                    }
                    moveAndClick(x: joinHit.x, y: joinHit.y)
                    clickedMiniProgramJoin = true
                    usleep(2_200_000)
                }
            }
        }
        state = scanTMState()
    }

    if !state.needsPwd && !state.inMeeting && !meetingCode.isEmpty {
        if let url = URL(string: "wemeet://page/inmeeting?meeting_code=\(meetingCode)") {
            _ = NSWorkspace.shared.open(url)
            usleep(2_200_000)
        }
        state = scanTMState()
    }

    if !state.needsPwd && !state.inMeeting {
        for w in findTencentMeetingWindows() where !w.title.isEmpty || w.w != 720 {
            if let (elems, sx, sy) = ocrWindowByID(w.wid, winX: w.x, winY: w.y, winW: w.w, winH: w.h) {
                let txt = elems.compactMap { $0["text"] as? String }.joined(separator: " ")
                if !txt.contains("快速会议"),
                   let hit = findOCRPoint(elems, sx: sx, sy: sy, winX: w.x, winY: w.y, matching: ["使用电脑音频", "进入会议", "加入会议"]) {
                    if let tmApp = NSRunningApplication(processIdentifier: w.pid) {
                        _ = tmApp.unhide()
                        _ = tmApp.activate(options: [.activateIgnoringOtherApps])
                    }
                    usleep(180_000)
                    moveAndClick(x: hit.x, y: hit.y)
                    usleep(2_000_000)
                    state = scanTMState()
                    break
                }
            }
        }
    }

    if state.needsPwd, let pw = state.pwdWin {
        if password.isEmpty {
            writeJSON([
                "ok": true,
                "joined": false,
                "needsPassword": true,
                "meetingCode": meetingCode,
                "passwordWindowID": pw.wid,
                "clickedCardPoint": clickedCardPt as Any,
                "clickedMiniProgramJoin": clickedMiniProgramJoin,
            ])
            return
        }
        if let tmApp = NSRunningApplication(processIdentifier: pw.pid) {
            _ = tmApp.unhide()
            _ = tmApp.activate(options: [.activateIgnoringOtherApps])
        }
        usleep(250_000)
        if let fpt = state.pwdFieldPt {
            moveAndClick(x: fpt.0, y: fpt.1)
            usleep(150_000)
            let pb = NSPasteboard.general
            let origClip = pb.string(forType: .string)
            pb.clearContents()
            pb.setString(password, forType: .string)
            postKey(keyCode: kKeyA, flags: .maskCommand)
            usleep(50_000)
            postKey(keyCode: kKeyV, flags: .maskCommand)
            usleep(250_000)
            pb.clearContents()
            if let orig = origClip { pb.setString(orig, forType: .string) }
        }
        if let bpt = state.joinBtnPt {
            moveAndClick(x: bpt.0, y: bpt.1)
            usleep(2_600_000)
        }
        state = scanTMState()
        var setupRes: [String: Any] = [:]
        if state.inMeeting || !state.needsPwd {
            setupRes = ensureTencentMeetingSubtitlesAndYuanbao()
        }
        writeJSON([
            "ok": true,
            "joined": state.inMeeting || !state.needsPwd,
            "needsPassword": state.needsPwd,
            "wrongPassword": state.needsPwd,
            "inMeeting": state.inMeeting,
            "meetingCode": meetingCode,
            "clickedCardPoint": clickedCardPt as Any,
            "clickedMiniProgramJoin": clickedMiniProgramJoin,
            "meetingSetup": setupRes,
        ])
        return
    }

    var setupRes2: [String: Any] = [:]
    if state.inMeeting {
        setupRes2 = ensureTencentMeetingSubtitlesAndYuanbao()
    }
    writeJSON([
        "ok": true,
        "joined": state.inMeeting,
        "needsPassword": state.needsPwd,
        "inMeeting": state.inMeeting,
        "meetingCode": meetingCode,
        "clickedCardPoint": clickedCardPt as Any,
        "clickedMiniProgramJoin": clickedMiniProgramJoin,
        "meetingSetup": setupRes2,
    ])
}

func cmdExtractVideoFrames(options: [String: String]) {
    guard let videoPath = options["video"], !videoPath.isEmpty else {
        failJSON("Missing --video <path>", code: "missing_argument")
    }
    guard FileManager.default.fileExists(atPath: videoPath) else {
        failJSON("Video file not found: \(videoPath)", code: "file_not_found")
    }
    let outDir = options["out-dir"] ?? NSTemporaryDirectory()
    let count = max(1, min(12, Int(options["count"] ?? "3") ?? 3))
    let url = URL(fileURLWithPath: videoPath)
    let asset = AVURLAsset(url: url)
    let durationSec = max(0.0, CMTimeGetSeconds(asset.duration))
    let generator = AVAssetImageGenerator(asset: asset)
    generator.appliesPreferredTrackTransform = true
    generator.maximumSize = CGSize(width: 1280, height: 1280)
    generator.requestedTimeToleranceBefore = CMTime(seconds: 0.35, preferredTimescale: 600)
    generator.requestedTimeToleranceAfter = CMTime(seconds: 0.35, preferredTimescale: 600)

    try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
    var frames: [[String: Any]] = []
    for idx in 0..<count {
        let frac = count == 1 ? 0.15 : (0.10 + 0.80 * Double(idx) / Double(count - 1))
        let targetSec = durationSec > 0.2 ? durationSec * frac : 0.0
        let t = CMTime(seconds: targetSec, preferredTimescale: 600)
        var actual = CMTime.zero
        if let cgImg = try? generator.copyCGImage(at: t, actualTime: &actual) {
            let outPath = URL(fileURLWithPath: outDir).appendingPathComponent(String(format: "frame_%02d.png", idx + 1)).path
            if saveCGImageAsPNG(cgImg, to: outPath) {
                frames.append([
                    "index": idx + 1,
                    "timestampSeconds": (CMTimeGetSeconds(actual) * 100.0).rounded() / 100.0,
                    "path": outPath,
                    "width": cgImg.width,
                    "height": cgImg.height,
                ])
            }
        }
    }
    writeJSON([
        "ok": !frames.isEmpty,
        "videoPath": videoPath,
        "durationSeconds": (durationSec * 100.0).rounded() / 100.0,
        "frameCount": frames.count,
        "frames": frames,
    ])
}

// MARK: - CoreAudio Input Switching & WeChat / WeCom VoIP Calling

struct AudioInputDeviceInfo {
    let deviceID: AudioDeviceID
    let uid: String
    let name: String
}

func audioDeviceHasInputStreams(_ devID: AudioDeviceID) -> Bool {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreams,
        mScope: kAudioDevicePropertyScopeInput,
        mElement: kAudioObjectPropertyElementMain
    )
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(devID, &addr, 0, nil, &size) == noErr else {
        return false
    }
    return size > 0
}

func audioDeviceCFStringProperty(_ devID: AudioDeviceID, selector: AudioObjectPropertySelector) -> String {
    var addr = AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var cfRef: Unmanaged<CFString>? = nil
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let status = withUnsafeMutablePointer(to: &cfRef) { ptr in
        AudioObjectGetPropertyData(devID, &addr, 0, nil, &size, ptr)
    }
    guard status == noErr, let unwrapped = cfRef else { return "" }
    return unwrapped.takeRetainedValue() as String
}

func listAudioInputDevices() -> [AudioInputDeviceInfo] {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size) == noErr, size > 0 else {
        return []
    }
    let count = Int(size) / MemoryLayout<AudioDeviceID>.size
    var ids = [AudioDeviceID](repeating: 0, count: count)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids) == noErr else {
        return []
    }
    var out: [AudioInputDeviceInfo] = []
    for devID in ids where audioDeviceHasInputStreams(devID) {
        let uid = audioDeviceCFStringProperty(devID, selector: kAudioDevicePropertyDeviceUID)
        let name = audioDeviceCFStringProperty(devID, selector: kAudioObjectPropertyName)
        if !uid.isEmpty || !name.isEmpty {
            out.append(AudioInputDeviceInfo(deviceID: devID, uid: uid, name: name))
        }
    }
    return out
}

func getDefaultInputAudioDevice(from devices: [AudioInputDeviceInfo]) -> AudioInputDeviceInfo? {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var devID: AudioDeviceID = 0
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &devID) == noErr else {
        return nil
    }
    if let match = devices.first(where: { $0.deviceID == devID }) {
        return match
    }
    let uid = audioDeviceCFStringProperty(devID, selector: kAudioDevicePropertyDeviceUID)
    let name = audioDeviceCFStringProperty(devID, selector: kAudioObjectPropertyName)
    return AudioInputDeviceInfo(deviceID: devID, uid: uid, name: name)
}

func setDefaultInputAudioDevice(_ devID: AudioDeviceID) -> OSStatus {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var target = devID
    let size = UInt32(MemoryLayout<AudioDeviceID>.size)
    return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, size, &target)
}

func audioDeviceToDict(_ dev: AudioInputDeviceInfo) -> [String: Any] {
    return [
        "deviceID": Int(dev.deviceID),
        "uid": dev.uid,
        "name": dev.name,
        "isVirtual": dev.uid.contains("Oray") || dev.uid.contains("WMAudio") || dev.name.contains("Virtual") || dev.name.contains("WeMeet"),
    ]
}

func cmdAudioDevices() {
    let devs = listAudioInputDevices()
    let cur = getDefaultInputAudioDevice(from: devs)
    writeJSON([
        "ok": true,
        "defaultInput": cur.map { audioDeviceToDict($0) } as Any,
        "inputDevices": devs.map { audioDeviceToDict($0) },
    ])
}

func restoreInputDeviceIfSaved(saveFile: String) -> [String: Any]? {
    let url = URL(fileURLWithPath: saveFile)
    guard let data = try? Data(contentsOf: url),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return nil
    }
    let savedUid = (obj["uid"] as? String) ?? ""
    let savedName = (obj["name"] as? String) ?? ""
    let devs = listAudioInputDevices()
    guard let match = devs.first(where: { !$0.uid.isEmpty && $0.uid == savedUid })
        ?? devs.first(where: { !$0.name.isEmpty && $0.name == savedName }) else {
        return ["ok": false, "restored": false, "error": "Saved input device not found: \(savedUid)", "uid": savedUid]
    }
    let st = setDefaultInputAudioDevice(match.deviceID)
    if st == noErr {
        try? FileManager.default.removeItem(at: url)
        return ["ok": true, "restored": true, "defaultInput": audioDeviceToDict(match)]
    }
    return ["ok": false, "restored": false, "osStatus": Int(st), "uid": savedUid]
}

func cmdSetInputDevice(flags: Set<String>, options: [String: String]) {
    let restore = flags.contains("restore") || options["restore"] == "1"
    let saveFile = (options["save-file"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)

    if restore {
        if saveFile.isEmpty {
            failJSON("Missing --save-file for --restore", code: "missing_argument")
        }
        if let res = restoreInputDeviceIfSaved(saveFile: saveFile) {
            writeJSON(res, exitCode: (res["ok"] as? Bool) == true ? 0 : 1)
        } else {
            writeJSON(["ok": true, "restored": false, "reason": "no_saved_file"])
        }
    }

    let query = (options["uid"] ?? options["name"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if query.isEmpty {
        failJSON("Missing --uid <deviceUID> (or --restore --save-file <path>)", code: "missing_argument")
    }
    let devs = listAudioInputDevices()
    let prev = getDefaultInputAudioDevice(from: devs)
    if !saveFile.isEmpty, let cur = prev {
        let saveURL = URL(fileURLWithPath: saveFile)
        let isVirtual = cur.uid.contains("Oray") || cur.uid.contains("WMAudio") || cur.name.contains("Virtual") || cur.name.contains("WeMeet")
        if !FileManager.default.fileExists(atPath: saveURL.path), !isVirtual {
            try? FileManager.default.createDirectory(at: saveURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let data = try? JSONSerialization.data(withJSONObject: audioDeviceToDict(cur), options: [.prettyPrinted]) {
                try? data.write(to: saveURL)
            }
        }
    }
    let low = query.lowercased()
    guard let match = devs.first(where: { $0.uid == query })
        ?? devs.first(where: { $0.name == query })
        ?? devs.first(where: { $0.uid.lowercased().contains(low) || $0.name.lowercased().contains(low) }) else {
        failJSON("Audio input device not found: \(query)", code: "device_not_found", extra: [
            "availableInputs": devs.map { audioDeviceToDict($0) },
        ])
    }
    let st = setDefaultInputAudioDevice(match.deviceID)
    guard st == noErr else {
        failJSON("Failed to set default input device (OSStatus \(st))", code: "coreaudio_set_failed")
    }
    let nowCur = getDefaultInputAudioDevice(from: listAudioInputDevices()) ?? match
    writeJSON([
        "ok": true,
        "previousInput": prev.map { audioDeviceToDict($0) } as Any,
        "defaultInput": audioDeviceToDict(nowCur),
        "savedFile": saveFile.isEmpty ? NSNull() : saveFile,
    ])
}

func captureOnScreenRect(_ rect: CGRect) -> CGImage? {
    guard rect.width >= 4, rect.height >= 4 else { return nil }
    return CGWindowListCreateImage(rect, .optionOnScreenOnly, kCGNullWindowID, [.bestResolution])
}

func captureWindowByID(_ wid: UInt32) -> CGImage? {
    return CGWindowListCreateImage(.null, .optionIncludingWindow, wid, [.boundsIgnoreFraming, .bestResolution])
}

func ocrOnScreenRect(_ rect: CGRect, languages: [String] = ["zh-Hans", "en-US"]) -> ([[String: Any]], Double, Double, CGImage)? {
    guard let img = captureOnScreenRect(rect),
          let elems = try? runVisionOCR(cgImage: img, languages: languages) else {
        return nil
    }
    let sx = Double(img.width) / max(1.0, Double(rect.width))
    let sy = Double(img.height) / max(1.0, Double(rect.height))
    return (elems, sx, sy, img)
}

func ocrWindowByID(_ wid: UInt32, winRect: CGRect, preferOnScreenComposite: Bool = false, languages: [String] = ["zh-Hans", "en-US"]) -> ([[String: Any]], Double, Double, CGImage)? {
    let captured: CGImage?
    if preferOnScreenComposite {
        captured = captureOnScreenRect(winRect)
    } else {
        captured = captureWindowByID(wid) ?? captureOnScreenRect(winRect)
    }
    guard let img = captured,
          let elems = try? runVisionOCR(cgImage: img, languages: languages) else {
        return nil
    }
    let sx = Double(img.width) / max(1.0, Double(winRect.width))
    let sy = Double(img.height) / max(1.0, Double(winRect.height))
    return (elems, sx, sy, img)
}

func ocrWindowSubRect(_ wid: UInt32, winRect: CGRect, subRect: CGRect, languages: [String] = ["zh-Hans", "en-US"]) -> ([[String: Any]], Double, Double, CGImage, CGRect)? {
    let clipped = subRect.intersection(winRect)
    guard !clipped.isNull, clipped.width >= 8, clipped.height >= 8 else { return nil }
    if let fullImg = captureWindowByID(wid) {
        let scaleX = Double(fullImg.width) / max(1.0, Double(winRect.width))
        let scaleY = Double(fullImg.height) / max(1.0, Double(winRect.height))
        let pxRect = CGRect(
            x: max(0.0, (Double(clipped.minX) - Double(winRect.minX)) * scaleX),
            y: max(0.0, (Double(clipped.minY) - Double(winRect.minY)) * scaleY),
            width: max(4.0, Double(clipped.width) * scaleX),
            height: max(4.0, Double(clipped.height) * scaleY)
        ).intersection(CGRect(x: 0, y: 0, width: fullImg.width, height: fullImg.height))
        if !pxRect.isNull, pxRect.width >= 4, pxRect.height >= 4,
           let cropped = fullImg.cropping(to: pxRect),
           let elems = try? runVisionOCR(cgImage: cropped, languages: languages) {
            let sx = Double(cropped.width) / max(1.0, Double(clipped.width))
            let sy = Double(cropped.height) / max(1.0, Double(clipped.height))
            return (elems, sx, sy, cropped, clipped)
        }
    }
    if let (elems, sx, sy, img) = ocrOnScreenRect(clipped, languages: languages) {
        return (elems, sx, sy, img, clipped)
    }
    return nil
}

func wakeAndActivateApp(pid: pid_t, kind: AppKind) {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/caffeinate")
    proc.arguments = ["-u", "-t", "5"]
    proc.standardOutput = FileHandle.nullDevice
    proc.standardError = FileHandle.nullDevice
    try? proc.run()

    let axApp = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(axApp, 0.3)
    _ = AXUIElementSetAttributeValue(axApp, kAXFrontmostAttribute as CFString, kCFBooleanTrue)

    let wasFront = isAppFrontmost(kind).0
    if let app = NSRunningApplication(processIdentifier: pid) {
        _ = app.unhide()
        _ = app.activate(options: [.activateIgnoringOtherApps])
    }
    for _ in 0..<4 {
        if isAppFrontmost(kind).0 { break }
        usleep(80_000)
    }
    if !isAppFrontmost(kind).0 {
        let bidToActivate = NSRunningApplication(processIdentifier: pid)?.bundleIdentifier ?? kind.bundleID
        let osa = Process()
        osa.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        osa.arguments = ["-e", "tell application id \"\(bidToActivate)\" to activate"]
        osa.standardOutput = FileHandle.nullDevice
        osa.standardError = FileHandle.nullDevice
        try? osa.run()
        osa.waitUntilExit()
        for _ in 0..<6 {
            if isAppFrontmost(kind).0 { break }
            usleep(80_000)
        }
        usleep(350_000)
    } else {
        usleep(wasFront ? 180_000 : 480_000)
    }
}

func preciseClick(x: Double, y: Double) {
    let pt = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)
    CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(60_000)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(50_000)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(40_000)
}

func nudgeSmallForeignOverlaysAway(from targetRect: CGRect, excludingPID pid: pid_t) {
    let findOverlaps: () -> [(pid: pid_t, wid: UInt32, rect: CGRect)] = {
        var found: [(pid: pid_t, wid: UInt32, rect: CGRect)] = []
        for entry in copyOnScreenWindowInfo() {
            guard let p = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value, p != pid,
                  let wid = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
                  let bounds = entry[kCGWindowBounds as String] as? [String: Any],
                  let w = (bounds["Width"] as? NSNumber)?.doubleValue,
                  let h = (bounds["Height"] as? NSNumber)?.doubleValue else {
                continue
            }
            let alpha = (entry[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1.0
            guard alpha > 0.05 else { continue }
            let layer = (entry[kCGWindowLayer as String] as? Int) ?? 0
            guard layer > 0 && layer <= 2500 else { continue }
            guard w >= 80 && w <= 600 && h >= 60 && h <= 600 else { continue }
            let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
            let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
            let r = CGRect(x: x, y: y, width: w, height: h)
            if r.intersects(targetRect) {
                found.append((p, wid, r))
            }
        }
        return found
    }

    let initialOverlaps = findOverlaps()
    if initialOverlaps.isEmpty { return }

    if AXIsProcessTrusted() {
        for item in initialOverlaps {
            let fAx = AXUIElementCreateApplication(item.pid)
            AXUIElementSetMessagingTimeout(fAx, 0.25)
            if let wins = axAttr(fAx, kAXWindowsAttribute) as? [AXUIElement] {
                for wEl in wins {
                    if let pt = axPoint(wEl, kAXPositionAttribute),
                       let sz = axSize(wEl, kAXSizeAttribute) {
                        let d = abs(Double(pt.x) - Double(item.rect.minX))
                            + abs(Double(pt.y) - Double(item.rect.minY))
                            + abs(Double(sz.width) - Double(item.rect.width))
                            + abs(Double(sz.height) - Double(item.rect.height))
                        if d <= 36.0 {
                            var newPt = CGPoint(x: 24.0, y: 560.0)
                            if let axPos = AXValueCreate(.cgPoint, &newPt) {
                                _ = AXUIElementSetAttributeValue(wEl, kAXPositionAttribute as CFString, axPos)
                            }
                            break
                        }
                    }
                }
            }
        }
        usleep(160_000)
    }

    let remaining = findOverlaps()
    guard !remaining.isEmpty else { return }
    let src = CGEventSource(stateID: .hidSystemState)
    for item in remaining {
        let start = CGPoint(x: Double(item.rect.midX), y: Double(item.rect.minY) + 18.0)
        let end = CGPoint(x: 160.0, y: 680.0)
        CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: start, mouseButton: .left)?.post(tap: .cghidEventTap)
        usleep(40_000)
        CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: start, mouseButton: .left)?.post(tap: .cghidEventTap)
        usleep(40_000)
        for step in 1...6 {
            let t = Double(step) / 6.0
            let cur = CGPoint(x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t)
            CGEvent(mouseEventSource: src, mouseType: .leftMouseDragged, mouseCursorPosition: cur, mouseButton: .left)?.post(tap: .cghidEventTap)
            usleep(28_000)
        }
        CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: end, mouseButton: .left)?.post(tap: .cghidEventTap)
        usleep(180_000)
    }
}

func collectForeignOverlayRects(excludingPID pid: pid_t) -> [CGRect] {
    var rects: [CGRect] = []
    for entry in copyOnScreenWindowInfo() {
        guard let p = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value, p != pid,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue else {
            continue
        }
        let alpha = (entry[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1.0
        guard alpha > 0.05 else { continue }
        let layer = (entry[kCGWindowLayer as String] as? Int) ?? 0
        guard layer > 0 && layer <= 2500 else { continue }
        if w >= 2400 && h >= 1300 { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        rects.append(CGRect(x: x, y: y, width: w, height: h))
    }
    return rects
}

func pidWindowIDs(pid: pid_t) -> Set<UInt32> {
    var out = Set<UInt32>()
    for e in copyOnScreenWindowInfo() {
        if let p = (e[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value, p == pid,
           let wid = (e[kCGWindowNumber as String] as? NSNumber)?.uint32Value {
            out.insert(wid)
        }
    }
    return out
}

func findNewPopupWindow(pid: pid_t, existing: Set<UInt32>) -> (wid: UInt32, rect: CGRect, layer: Int)? {
    var candidates: [(wid: UInt32, rect: CGRect, layer: Int)] = []
    for e in copyOnScreenWindowInfo() {
        guard let p = (e[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value, p == pid,
              let wid = (e[kCGWindowNumber as String] as? NSNumber)?.uint32Value, !existing.contains(wid),
              let bounds = e[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue else {
            continue
        }
        let alpha = (e[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1.0
        guard alpha > 0.05 else { continue }
        let layer = (e[kCGWindowLayer as String] as? Int) ?? 0
        guard layer >= 0 && layer <= 120 else { continue }
        guard w >= 60 && w <= 380 && h >= 36 && h <= 320 else { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        candidates.append((wid, CGRect(x: x, y: y, width: w, height: h), layer))
    }
    candidates.sort { a, b in
        if (a.layer > 0) != (b.layer > 0) { return a.layer > 0 }
        return (a.rect.width * a.rect.height) < (b.rect.width * b.rect.height)
    }
    if let best = candidates.first {
        return (best.wid, best.rect, best.layer)
    }
    return nil
}

func findColorCirclePoint(in cgImg: CGImage, winRect: CGRect, kind: String) -> (x: Double, y: Double, count: Int)? {
    let w = cgImg.width
    let h = cgImg.height
    guard w > 40, h > 30 else { return nil }
    var raw = [UInt8](repeating: 0, count: w * h * 4)
    guard let ctx = CGContext(
        data: &raw,
        width: w,
        height: h,
        bitsPerComponent: 8,
        bytesPerRow: w * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else { return nil }
    ctx.draw(cgImg, in: CGRect(x: 0, y: 0, width: w, height: h))

    let cell = 24
    var buckets: [String: (sumX: Double, sumY: Double, count: Int)] = [:]
    let startY = Int(Double(h) * 0.25)
    for py in stride(from: startY, to: h, by: 2) {
        let rowOff = py * w * 4
        for px in stride(from: 0, to: w, by: 2) {
            let i = rowOff + px * 4
            let r = Int(raw[i])
            let g = Int(raw[i + 1])
            let b = Int(raw[i + 2])
            let a = Int(raw[i + 3])
            guard a > 180 else { continue }
            let matched: Bool
            if kind == "green" {
                matched = g >= 135 && (g - r) >= 35 && (g - b) >= 20
            } else {
                matched = r >= 170 && (r - g) >= 55 && (r - b) >= 50
            }
            if matched {
                let key = "\(px / cell)_\(py / cell)"
                let prev = buckets[key] ?? (0.0, 0.0, 0)
                buckets[key] = (prev.sumX + Double(px), prev.sumY + Double(py), prev.count + 1)
            }
        }
    }
    guard let best = buckets.values.max(by: { $0.count < $1.count }), best.count >= 8 else {
        return nil
    }
    let estX = best.sumX / Double(best.count)
    let estY = best.sumY / Double(best.count)
    // Refine centroid across surrounding 3x3 cells (~72px)
    var fineX = 0.0
    var fineY = 0.0
    var fineCnt = 0
    for (_, bkt) in buckets where bkt.count >= 4 {
        let bx = bkt.sumX / Double(bkt.count)
        let by = bkt.sumY / Double(bkt.count)
        if abs(bx - estX) <= 44.0 && abs(by - estY) <= 44.0 {
            fineX += bkt.sumX
            fineY += bkt.sumY
            fineCnt += bkt.count
        }
    }
    let cx = (fineCnt > 0 ? fineX / Double(fineCnt) : estX)
    let cy = (fineCnt > 0 ? fineY / Double(fineCnt) : estY)
    let screenX = Double(winRect.minX) + (cx / Double(w)) * Double(winRect.width)
    let screenY = Double(winRect.minY) + (cy / Double(h)) * Double(winRect.height)
    return (screenX, screenY, fineCnt > 0 ? fineCnt : best.count)
}

func scanVoipWindows(appFilter: String, activateOwner: Bool = false) -> [String: Any] {
    let wantWeChat = appFilter == "all" || appFilter == "omni" || appFilter == "wechat"
    let wantWeCom = appFilter == "all" || appFilter == "omni" || appFilter == "wecom"
    let wantFeishu = appFilter == "omni" || appFilter == "feishu" || appFilter == "lark"
    let wantDingTalk = appFilter == "omni" || appFilter == "dingtalk" || appFilter == "ding"

    if activateOwner {
        if wantWeChat && !wantWeCom && !wantFeishu && !wantDingTalk, let app = findBestRunningApp(for: .wechat) {
            wakeAndActivateApp(pid: app.processIdentifier, kind: .wechat)
        } else if wantWeCom && !wantWeChat && !wantFeishu && !wantDingTalk, let app = findBestRunningApp(for: .wecom) {
            wakeAndActivateApp(pid: app.processIdentifier, kind: .wecom)
        } else if wantFeishu && !wantWeChat && !wantWeCom && !wantDingTalk, let app = findBestRunningApp(for: .feishu) {
            wakeAndActivateApp(pid: app.processIdentifier, kind: .feishu)
        } else if wantDingTalk && !wantWeChat && !wantWeCom && !wantFeishu, let app = findBestRunningApp(for: .dingtalk) {
            wakeAndActivateApp(pid: app.processIdentifier, kind: .dingtalk)
        }
    }

    let wechatPIDs = wantWeChat ? Set(findRunningApps(for: .wechat).map { $0.processIdentifier }) : Set<pid_t>()
    let wecomPIDs = wantWeCom ? Set(findRunningApps(for: .wecom).map { $0.processIdentifier }) : Set<pid_t>()
    let feishuPIDs = wantFeishu ? Set(findRunningApps(for: .feishu).map { $0.processIdentifier }) : Set<pid_t>()
    let dingtalkPIDs = wantDingTalk ? Set(findRunningApps(for: .dingtalk).map { $0.processIdentifier }) : Set<pid_t>()

    var candidates: [(appId: String, pid: pid_t, wid: UInt32, layer: Int, title: String, rect: CGRect, isOnScreen: Bool)] = []
    for entry in copyOnScreenWindowInfo() {
        guard let pid = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              let wid = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value else {
            continue
        }
        let owner = (entry[kCGWindowOwnerName as String] as? String) ?? ""
        let appId: String
        if wantWeCom && (wecomPIDs.contains(pid) || owner == "企业微信" || owner == "WeCom" || owner == "WeWork") {
            appId = "wecom"
        } else if wantWeChat && (wechatPIDs.contains(pid) || owner == "微信" || owner == "WeChat" || owner == "WeChatVoIP") {
            appId = "wechat"
        } else if wantFeishu && (feishuPIDs.contains(pid) || owner == "飞书" || owner == "Lark" || owner == "Feishu" || owner == "飞书会议") {
            appId = "feishu"
        } else if wantDingTalk && (dingtalkPIDs.contains(pid) || owner == "钉钉" || owner == "DingTalk") {
            appId = "dingtalk"
        } else {
            continue
        }

        let alpha = (entry[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1.0
        guard alpha > 0.05 else { continue }
        let layer = (entry[kCGWindowLayer as String] as? Int) ?? 0
        guard layer >= 0 && layer <= 2500 else { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let title = (entry[kCGWindowName as String] as? String) ?? ""
        let isOnScreen = (entry[kCGWindowIsOnscreen as String] as? Bool) ?? true

        // Exclude known large main / popout chat windows unless titled for call
        if title == "openbot" || title == "消息阅读" { continue }
        let looksCallTitle = title.contains("通话") || title.contains("语音") || title.contains("视频") || title.contains("飞书会议")
        guard looksCallTitle || (w >= 160 && w <= 900 && h >= 60 && h <= 860) else { continue }
        // Skip auxiliary large panels unless explicitly titled as a call
        if !looksCallTitle && w > 900 { continue }

        candidates.append((appId, pid, wid, layer, title, CGRect(x: x, y: y, width: w, height: h), isOnScreen))
    }

    // Prefer on-screen floating/small call toasts and titled windows first
    candidates.sort { a, b in
        if a.isOnScreen != b.isOnScreen { return a.isOnScreen }
        if (a.layer > 0) != (b.layer > 0) { return a.layer > 0 }
        return (a.rect.width * a.rect.height) < (b.rect.width * b.rect.height)
    }

    var matches: [[String: Any]] = []
    var primaryState = "idle"

    for c in candidates.prefix(12) {
        if c.layer > 0 && c.rect.width <= 500 && c.rect.height <= 320 {
            nudgeSmallForeignOverlaysAway(from: c.rect, excludingPID: c.pid)
        }
        let useComposite = (c.appId == "wecom" || (c.layer > 0 && c.layer != 21))
        guard let (elems, sx, sy, img) = ocrWindowByID(c.wid, winRect: c.rect, preferOnScreenComposite: useComposite) else { continue }
        let texts = elems.compactMap { $0["text"] as? String }
        let joined = texts.joined(separator: " ")

        let greenPt = findColorCirclePoint(in: img, winRect: c.rect, kind: "green")
        let redPt = findColorCirclePoint(in: img, winRect: c.rect, kind: "red")

        let acceptOCRInitial = findTMOCRPoint(elems, sx: sx, sy: sy, winX: Double(c.rect.minX), winY: Double(c.rect.minY), matching: ["接受", "接听", "同意"])

        if c.appId == "wecom" && c.layer > 0 && c.rect.width >= 240 && c.rect.width <= 420 && c.rect.height >= 110 && c.rect.height <= 240 {
            let toastPath = "/Volumes/SanDisk/Builds/WeChatBot/wecom_voip_toast.png"
            if !FileManager.default.fileExists(atPath: toastPath),
               let pngData = NSBitmapImageRep(cgImage: img).representation(using: .png, properties: [:]) {
                try? pngData.write(to: URL(fileURLWithPath: toastPath))
            }
        }

        let isOutgoingWaiting = joined.contains("等待对方") || joined.contains("等待") || joined.contains("接受邀请") || joined.contains("正在呼叫") || joined.contains("呼叫中") || joined.contains("连接中")
        let hasTimer = joined.range(of: "\\b\\d{2}:\\d{2}\\b", options: .regularExpression) != nil
        let hasHangupWord = joined.contains("挂断") || joined.contains("取消") || joined.contains("拒绝")
        let hasCancelWithoutHangup = joined.contains("取消") && !joined.contains("挂断") && !hasTimer
        let hasIncomingWords = !isOutgoingWaiting && !hasCancelWithoutHangup && (joined.contains("邀请你") || joined.contains("接听") || joined.contains("接受") || joined.contains("同意") || joined.contains("来电"))
        let hasCallWords = joined.contains("语音通话") || joined.contains("语音聊天") || joined.contains("视频通话") || joined.contains("视频聊天") || joined.contains("通话中") || joined.contains("语音") || joined.contains("视频") || isOutgoingWaiting || joined.contains("邀请你")
        let hasInCallControls = (joined.contains("麦克风") || joined.contains("静音") || joined.contains("扬声器") || joined.contains("收起"))

        let isConnectedScreen = hasTimer || joined.contains("通话中") || joined.contains("挂断") || joined.contains("演示屏幕") || joined.contains("添加成员")

        var callStatus = "none"
        if isConnectedScreen {
            callStatus = "connected"
        } else if isOutgoingWaiting || (hasCallWords && hasCancelWithoutHangup && greenPt == nil) {
            callStatus = "dialing"
        } else if (greenPt != nil && redPt != nil) || (hasIncomingWords && (hasCallWords || greenPt != nil)) || (c.layer > 0 && greenPt != nil) {
            callStatus = "ringing_incoming"
        } else if (hasCallWords && redPt != nil && !hasIncomingWords && !hasCancelWithoutHangup) || (hasInCallControls && (redPt != nil || hasHangupWord)) {
            callStatus = "connected"
        } else if c.layer > 0 && hasCallWords && redPt != nil {
            callStatus = "dialing"
        }

        if callStatus == "none" && c.appId == "wecom" && c.layer > 0 && c.rect.width >= 240 && c.rect.width <= 420 && c.rect.height >= 110 && c.rect.height <= 240 {
            if greenPt != nil || acceptOCRInitial != nil || joined.contains("语音") || joined.contains("通话") || joined.contains("视频") || joined.contains("@微信") {
                callStatus = "ringing_incoming"
            }
        }

        if callStatus == "none" { continue }

        let acceptOCR = (callStatus == "ringing_incoming") ? acceptOCRInitial : nil
        let hangupOCR = findTMOCRPoint(elems, sx: sx, sy: sy, winX: Double(c.rect.minX), winY: Double(c.rect.minY), matching: ["挂断", "拒绝", "取消"])

        var info: [String: Any] = [
            "appId": c.appId,
            "pid": c.pid,
            "windowID": c.wid,
            "layer": c.layer,
            "isOnScreen": c.isOnScreen,
            "title": c.title,
            "bounds": ["x": Double(c.rect.minX), "y": Double(c.rect.minY), "width": Double(c.rect.width), "height": Double(c.rect.height)],
            "callStatus": callStatus,
            "ocrSnippet": String(joined.prefix(160)),
        ]
        if callStatus == "ringing_incoming", let gpt = greenPt {
            info["greenButton"] = ["x": gpt.x, "y": gpt.y, "pixels": gpt.count] as [String: Any]
        } else if callStatus == "ringing_incoming", let aocr = acceptOCR {
            info["greenButton"] = ["x": aocr.x, "y": aocr.y, "source": "ocr"] as [String: Any]
        }
        if let rpt = redPt {
            info["redButton"] = ["x": rpt.x, "y": rpt.y, "pixels": rpt.count] as [String: Any]
        } else if let hocr = hangupOCR {
            info["redButton"] = ["x": hocr.x, "y": hocr.y, "source": "ocr"] as [String: Any]
        }

        matches.append(info)
        if primaryState == "idle" || callStatus == "connected" || (callStatus == "ringing_incoming" && primaryState != "connected") {
            primaryState = callStatus
        }
    }

    return [
        "ok": true,
        "callStatus": primaryState,
        "matchCount": matches.count,
        "calls": matches,
    ]
}

func dismissWeComModalSheetIfPresent(pid: pid_t) {
    guard AXIsProcessTrusted() else { return }
    let axApp = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(axApp, 0.35)
    var q: [AXUIElement] = [axApp]
    var qi = 0
    var hasSheet = false
    var cancelButtons: [AXUIElement] = []
    while qi < q.count && qi < 140 {
        let el = q[qi]; qi += 1
        AXUIElementSetMessagingTimeout(el, 0.25)
        let role = axString(el, kAXRoleAttribute) ?? ""
        if role == kAXSheetRole as String {
            hasSheet = true
        } else if role == kAXButtonRole as String,
                  let title = axString(el, kAXTitleAttribute),
                  title == "取消" || title == "关闭" {
            // Walk up up to 4 ancestors to see if nested inside an AXSheet
            var cur = el
            var inSheet = false
            for _ in 0..<4 {
                var parentRef: CFTypeRef?
                if AXUIElementCopyAttributeValue(cur, kAXParentAttribute as CFString, &parentRef) == .success,
                   let p = parentRef {
                    let pEl = p as! AXUIElement
                    if axString(pEl, kAXRoleAttribute) == kAXSheetRole as String {
                        inSheet = true
                        break
                    }
                    cur = pEl
                } else {
                    break
                }
            }
            if inSheet {
                _ = AXUIElementPerformAction(el, kAXPressAction as CFString)
                usleep(280_000)
                return
            }
            cancelButtons.append(el)
        }
        q.append(contentsOf: axChildren(el))
    }
    if hasSheet, let btn = cancelButtons.first {
        _ = AXUIElementPerformAction(btn, kAXPressAction as CFString)
        usleep(280_000)
    }
}

func cmdVoiceCall(flags: Set<String>, options: [String: String]) {
    let action = (options["action"] ?? "status").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let dryRun = flags.contains("dry-run") || options["dry-run"] == "1"
    let callType = (options["call-type"] ?? "audio").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let requestedApp = (options["app-id"] ?? "all").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let saveFile = (options["save-file"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)

    if action == "status" {
        let st = scanVoipWindows(appFilter: requestedApp, activateOwner: flags.contains("activate-scan"))
        writeJSON(st)
    }

    if action == "answer" {
        var scan = scanVoipWindows(appFilter: requestedApp, activateOwner: false)
        var calls = (scan["calls"] as? [[String: Any]]) ?? []
        if calls.isEmpty && requestedApp == "all" {
            for candidateApp in ["wecom", "wechat"] {
                let s = scanVoipWindows(appFilter: candidateApp, activateOwner: true)
                if !((s["calls"] as? [[String: Any]]) ?? []).isEmpty {
                    scan = s
                    calls = (s["calls"] as? [[String: Any]]) ?? []
                    break
                }
            }
        }
        guard let incoming = calls.first(where: { ($0["callStatus"] as? String) == "ringing_incoming" }) ?? calls.first,
              let g = incoming["greenButton"] as? [String: Any],
              let gx = g["x"] as? Double, let gy = g["y"] as? Double else {
            failJSON("No incoming VoIP call with answer button found.", code: "no_incoming_call", extra: ["scan": scan])
        }
        if dryRun {
            writeJSON(["ok": true, "dryRun": true, "action": "answer", "targetCall": incoming])
        }
        let targetAppId = (incoming["appId"] as? String) ?? requestedApp
        let targetKind: AppKind = AppKind.fromCLI(targetAppId) ?? .wechat
        if let pidNum = incoming["pid"] as? pid_t {
            if let bDict = incoming["bounds"] as? [String: Any],
               let bx = bDict["x"] as? Double, let by = bDict["y"] as? Double,
               let bw = bDict["width"] as? Double, let bh = bDict["height"] as? Double {
                nudgeSmallForeignOverlaysAway(from: CGRect(x: bx, y: by, width: bw, height: bh), excludingPID: pidNum)
            }
            wakeAndActivateApp(pid: pidNum, kind: targetKind)
        }
        // Re-scan after wake/activation in case bounds shifted slightly during Space switch
        let freshScan = scanVoipWindows(appFilter: targetAppId, activateOwner: false)
        let freshCall = ((freshScan["calls"] as? [[String: Any]]) ?? []).first { ($0["windowID"] as? UInt32) == (incoming["windowID"] as? UInt32) } ?? ((freshScan["calls"] as? [[String: Any]]) ?? []).first
        let clickX = ((freshCall?["greenButton"] as? [String: Any])?["x"] as? Double) ?? gx
        let clickY = ((freshCall?["greenButton"] as? [String: Any])?["y"] as? Double) ?? gy
        preciseClick(x: clickX, y: clickY)
        usleep(1_050_000)
        let after = scanVoipWindows(appFilter: targetAppId, activateOwner: false)
        writeJSON([
            "ok": true,
            "answered": true,
            "clickPoint": ["x": clickX, "y": clickY],
            "afterState": after,
        ])
    }

    if action == "hangup" {
        var scan = scanVoipWindows(appFilter: requestedApp, activateOwner: false)
        var calls = (scan["calls"] as? [[String: Any]]) ?? []
        if calls.isEmpty && requestedApp == "all" {
            for candidateApp in ["wechat", "wecom"] {
                let s = scanVoipWindows(appFilter: candidateApp, activateOwner: true)
                if !((s["calls"] as? [[String: Any]]) ?? []).isEmpty {
                    scan = s
                    calls = (s["calls"] as? [[String: Any]]) ?? []
                    break
                }
            }
        }
        var hungUpCount = 0
        var restoredAudio: [String: Any]? = nil
        if !dryRun {
            for c in calls {
                if let r = c["redButton"] as? [String: Any], let rx = r["x"] as? Double, let ry = r["y"] as? Double {
                    let cAppId = (c["appId"] as? String) ?? "wechat"
                    let cKind: AppKind = AppKind.fromCLI(cAppId) ?? .wechat
                    if let pidNum = c["pid"] as? pid_t {
                        if let bDict = c["bounds"] as? [String: Any],
                           let bx = bDict["x"] as? Double, let by = bDict["y"] as? Double,
                           let bw = bDict["width"] as? Double, let bh = bDict["height"] as? Double {
                            nudgeSmallForeignOverlaysAway(from: CGRect(x: bx, y: by, width: bw, height: bh), excludingPID: pidNum)
                        }
                        wakeAndActivateApp(pid: pidNum, kind: cKind)
                    }
                    let freshScan = scanVoipWindows(appFilter: cAppId, activateOwner: false)
                    let freshCall = ((freshScan["calls"] as? [[String: Any]]) ?? []).first { ($0["windowID"] as? UInt32) == (c["windowID"] as? UInt32) } ?? ((freshScan["calls"] as? [[String: Any]]) ?? []).first
                    let clickX = ((freshCall?["redButton"] as? [String: Any])?["x"] as? Double) ?? rx
                    let clickY = ((freshCall?["redButton"] as? [String: Any])?["y"] as? Double) ?? ry
                    preciseClick(x: clickX, y: clickY)
                    hungUpCount += 1
                    usleep(480_000)
                }
            }
            if !saveFile.isEmpty {
                restoredAudio = restoreInputDeviceIfSaved(saveFile: saveFile)
            }
        }
        let after = scanVoipWindows(appFilter: requestedApp, activateOwner: false)
        writeJSON([
            "ok": true,
            "dryRun": dryRun,
            "hungUp": hungUpCount > 0,
            "hungUpCount": hungUpCount,
            "restoredAudio": restoredAudio as Any,
            "afterState": after,
        ])
    }

    if action == "dial" {
        guard AXIsProcessTrusted() else {
            failJSON("Accessibility permission (AXIsProcessTrusted) is not granted.", code: "ax_permission_denied")
        }
        let (_, targetKind) = resolveTargetApp(options: options, allowWindowLookupWhenOmitted: true)
        let windows = listWindows(for: targetKind)
        guard let targetWin = selectTargetWindow(in: windows, options: options) else {
            failJSON("No matching visible \(targetKind.appLabel) window found.", code: "window_not_found", extra: ["appId": targetKind.appId])
        }

        if targetKind == .wechat {
            var winX = targetWin.x
            var winY = targetWin.y
            var winW = targetWin.width
            var winH = targetWin.height
            let displayBounds = CGDisplayBounds(CGMainDisplayID())
            let maxScreenX = Double(displayBounds.maxX)

            var callBtnX = winX + winW - 66.0
            var callBtnY = winY + 54.0
            if dryRun {
                writeJSON([
                    "ok": true,
                    "dryRun": true,
                    "action": "dial",
                    "appId": "wechat",
                    "callType": callType,
                    "windowID": targetWin.windowID,
                    "windowTitle": targetWin.title,
                    "callButtonPoint": ["x": callBtnX, "y": callBtnY],
                    "needsRepositionOnScreen": callBtnX >= maxScreenX - 8.0,
                ] as [String: Any])
            }
            wakeAndActivateApp(pid: targetWin.pid, kind: .wechat)
            if let axWin = findAXWindow(pid: targetWin.pid, kind: .wechat, targetWin: targetWin, reqTitle: options["window-title"]) {
                let overlays = collectForeignOverlayRects(excludingPID: targetWin.pid)
                let callZone = CGRect(x: winX + winW - 260.0, y: winY, width: 260.0, height: 240.0)
                let offScreen = (winX + winW > maxScreenX - 6.0 || winX < 0.0)
                let blockedByOverlay = overlays.contains(where: { $0.intersects(callZone) })
                if offScreen || blockedByOverlay {
                    let candidates: [(Double, Double)] = [
                        (40.0, 80.0),
                        (40.0, 320.0),
                        (120.0, 80.0),
                        (max(8.0, min(maxScreenX - winW - 12.0, winX)), max(40.0, winY)),
                    ]
                    let chosen = candidates.first { cand in
                        let candZone = CGRect(x: cand.0 + winW - 260.0, y: cand.1, width: 260.0, height: 240.0)
                        return cand.0 + winW <= maxScreenX - 6.0 && !overlays.contains(where: { $0.intersects(candZone) })
                    } ?? (40.0, 80.0)
                    var newPt = CGPoint(x: chosen.0, y: chosen.1)
                    if let axPos = AXValueCreate(.cgPoint, &newPt) {
                        _ = AXUIElementSetAttributeValue(axWin, kAXPositionAttribute as CFString, axPos)
                        usleep(220_000)
                    }
                }
                _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
                _ = AXUIElementSetAttributeValue(axWin, kAXFocusedAttribute as CFString, kCFBooleanTrue)
                _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
                usleep(180_000)
                if let actualPt = axPoint(axWin, kAXPositionAttribute) {
                    winX = Double(actualPt.x)
                    winY = Double(actualPt.y)
                }
                if let actualSz = axSize(axWin, kAXSizeAttribute) {
                    winW = Double(actualSz.width)
                    winH = Double(actualSz.height)
                }
                callBtnX = winX + winW - 66.0
                callBtnY = winY + 54.0
            }

            let topOwnWid = copyOnScreenWindowInfo().first(where: {
                (($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value ?? 0) == targetWin.pid &&
                (($0[kCGWindowLayer as String] as? Int) ?? 0) == 0 &&
                ((($0[kCGWindowBounds as String] as? [String: Any])?["Height"] as? NSNumber)?.doubleValue ?? 0) > 100
            }).flatMap { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value }
            if topOwnWid != targetWin.windowID {
                preciseClick(x: winX + 180.0, y: winY + 16.0)
                usleep(180_000)
            }

            let existingWids = pidWindowIDs(pid: targetWin.pid)
            var immediateStatus = "idle"
            var foundPopup: (wid: UInt32, rect: CGRect, layer: Int)? = nil
            for _ in 0..<2 {
                preciseClick(x: callBtnX, y: callBtnY)
                usleep(620_000)
                let curScan = scanVoipWindows(appFilter: "wechat", activateOwner: false)
                immediateStatus = (curScan["callStatus"] as? String) ?? "idle"
                if immediateStatus != "idle" {
                    break
                }
                if let pop = findNewPopupWindow(pid: targetWin.pid, existing: existingWids) {
                    foundPopup = pop
                    break
                }
            }

            var menuPt: (Double, Double) = (winX + winW - 110.0, winY + (callType == "video" ? 130.0 : 95.0))
            var ocrClicked = false
            var popupDetected: [String: Any] = ["found": false]

            if immediateStatus == "idle" {
                let kws = callType == "video" ? ["视频聊天", "视频通话"] : ["语音聊天", "语音通话"]
                if let popup = foundPopup {
                    popupDetected = [
                        "found": true,
                        "windowID": popup.wid,
                        "layer": popup.layer,
                        "bounds": ["x": Double(popup.rect.minX), "y": Double(popup.rect.minY), "width": Double(popup.rect.width), "height": Double(popup.rect.height)],
                    ]
                    if let (pElems, psx, psy, _) = ocrWindowByID(popup.wid, winRect: popup.rect),
                       let hit = findTMOCRPoint(pElems, sx: psx, sy: psy, winX: Double(popup.rect.minX), winY: Double(popup.rect.minY), matching: kws) {
                        menuPt = (hit.x, hit.y)
                        ocrClicked = true
                    } else if popup.rect.height < 95 {
                        menuPt = (Double(popup.rect.midX), Double(popup.rect.midY))
                    } else {
                        let relY = Double(popup.rect.height) * (callType == "video" ? 0.68 : 0.37)
                        menuPt = (Double(popup.rect.midX), Double(popup.rect.minY) + relY)
                    }
                } else {
                    let dropRect = CGRect(
                        x: max(0.0, winX + winW - 230.0),
                        y: max(0.0, winY + 32.0),
                        width: 225.0,
                        height: 205.0
                    )
                    if let (mElems, msx, msy, _, actRect) = ocrWindowSubRect(targetWin.windowID, winRect: CGRect(x: winX, y: winY, width: winW, height: winH), subRect: dropRect),
                       let hit = findTMOCRPoint(mElems, sx: msx, sy: msy, winX: Double(actRect.minX), winY: Double(actRect.minY), matching: kws) {
                        menuPt = (hit.x, hit.y)
                        ocrClicked = true
                    }
                }
                preciseClick(x: menuPt.0, y: menuPt.1)
                usleep(1_300_000)
            }

            let callState = scanVoipWindows(appFilter: "wechat", activateOwner: false)
            writeJSON([
                "ok": true,
                "initiated": true,
                "directCallOpened": immediateStatus != "idle",
                "appId": "wechat",
                "callType": callType,
                "windowID": targetWin.windowID,
                "windowTitle": targetWin.title,
                "callButtonPoint": ["x": callBtnX, "y": callBtnY],
                "popupDetected": popupDetected,
                "menuPoint": ["x": menuPt.0, "y": menuPt.1, "ocrMatched": ocrClicked] as [String: Any],
                "callState": callState,
            ])
        } else {
            // WeCom / Feishu / DingTalk Electron & native dial flow
            let contactHint = (options["target"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if dryRun {
                writeJSON([
                    "ok": true,
                    "dryRun": true,
                    "action": "dial",
                    "appId": targetKind.appId,
                    "callType": callType,
                    "target": contactHint,
                    "windowID": targetWin.windowID,
                    "windowTitle": targetWin.title,
                ])
            }
            wakeAndActivateApp(pid: targetWin.pid, kind: targetKind)
            if targetKind == .wecom {
                dismissWeComModalSheetIfPresent(pid: targetWin.pid)
            }
            enableElectronAccessibility(pid: targetWin.pid, kind: targetKind)

            let targetWinRect = CGRect(x: targetWin.x, y: targetWin.y, width: targetWin.width, height: targetWin.height)
            if !contactHint.isEmpty {
                let sideRect = CGRect(
                    x: targetWin.x + 60.0,
                    y: targetWin.y + 45.0,
                    width: 280.0,
                    height: min(680.0, max(120.0, targetWin.height - 65.0))
                )
                if let (sElems, ssx, ssy, _, actRect) = ocrWindowSubRect(targetWin.windowID, winRect: targetWinRect, subRect: sideRect),
                   let hit = findTMOCRPoint(sElems, sx: ssx, sy: ssy, winX: Double(actRect.minX), winY: Double(actRect.minY), matching: [contactHint]) {
                    preciseClick(x: hit.x, y: hit.y)
                    usleep(420_000)
                } else if let (sElems, ssx, ssy, _) = ocrOnScreenRect(sideRect),
                          let hit = findTMOCRPoint(sElems, sx: ssx, sy: ssy, winX: Double(sideRect.minX), winY: Double(sideRect.minY), matching: [contactHint]) {
                    preciseClick(x: hit.x, y: hit.y)
                    usleep(420_000)
                }
            }

            // Look for voice/video call AXButton
            let axApp = AXUIElementCreateApplication(targetWin.pid)
            AXUIElementSetMessagingTimeout(axApp, 0.35)
            var callBtnCenter: (Double, Double)? = nil
            var q: [AXUIElement] = [axApp]
            var qi = 0
            let axKeywords = callType == "video" ? ["视频通话", "视频会议", "Video", "视频"] : ["语音通话", "发起语音", "Voice", "语音", "打电话"]
            while qi < q.count && qi < 420 && callBtnCenter == nil {
                let el = q[qi]; qi += 1
                AXUIElementSetMessagingTimeout(el, 0.25)
                if axString(el, kAXRoleAttribute) == kAXButtonRole as String {
                    let meta = [axString(el, kAXTitleAttribute) ?? "", axString(el, kAXDescriptionAttribute) ?? "", axString(el, kAXHelpAttribute) ?? ""].joined(separator: " ")
                    if axKeywords.contains(where: { meta.localizedCaseInsensitiveContains($0) }),
                       let pt = axPoint(el, kAXPositionAttribute),
                       let sz = axSize(el, kAXSizeAttribute),
                       Double(pt.x) > targetWin.x + 280.0 {
                        callBtnCenter = (Double(pt.x) + Double(sz.width) * 0.5, Double(pt.y) + Double(sz.height) * 0.5)
                        break
                    }
                }
                q.append(contentsOf: axChildren(el))
            }
            if callBtnCenter == nil && targetKind == .wecom {
                // Fallback: top-right phone/call icon position on WeCom chat pane
                callBtnCenter = (targetWin.x + targetWin.width - 78.0, targetWin.y + 46.0)
            }
            let existingCallWids = pidWindowIDs(pid: targetWin.pid)
            if let cpt = callBtnCenter {
                preciseClick(x: cpt.0, y: cpt.1)
                usleep(550_000)
                if let popup = findNewPopupWindow(pid: targetWin.pid, existing: existingCallWids),
                   popup.rect.width <= 320 && popup.rect.height <= 220,
                   let (pElems, psx, psy, _) = ocrWindowByID(popup.wid, winRect: popup.rect),
                   let hit = findTMOCRPoint(pElems, sx: psx, sy: psy, winX: Double(popup.rect.minX), winY: Double(popup.rect.minY), matching: axKeywords) {
                    preciseClick(x: hit.x, y: hit.y)
                    usleep(950_000)
                } else {
                    usleep(650_000)
                }
            } else {
                failJSON("No voice/video call AX button found in \(targetKind.appLabel) chat header.", code: "call_button_not_found", extra: ["appId": targetKind.appId, "windowID": targetWin.windowID])
            }
            let callState = scanVoipWindows(appFilter: targetKind.appId, activateOwner: false)
            writeJSON([
                "ok": true,
                "initiated": true,
                "appId": targetKind.appId,
                "callType": callType,
                "windowID": targetWin.windowID,
                "callButtonPoint": callBtnCenter.map { ["x": $0.0, "y": $0.1] } as Any,
                "callState": callState,
            ])
        }
    }

    failJSON("Unsupported --action '\(action)'. Expected status|dial|answer|hangup.", code: "unsupported_action")
}

// MARK: - Universal macOS App-Use Primitives (v2.6.0)

let universalMacKeyMap: [String: (CGKeyCode, Bool)] = [
    // Letters (US QWERTY)
    "a": (0, false), "s": (1, false), "d": (2, false), "f": (3, false),
    "h": (4, false), "g": (5, false), "z": (6, false), "x": (7, false),
    "c": (8, false), "v": (9, false), "b": (11, false), "q": (12, false),
    "w": (13, false), "e": (14, false), "r": (15, false), "y": (16, false),
    "t": (17, false), "o": (31, false), "u": (32, false), "i": (34, false),
    "p": (35, false), "l": (37, false), "j": (38, false), "k": (40, false),
    "n": (45, false), "m": (46, false),
    // Digits
    "1": (18, false), "2": (19, false), "3": (20, false), "4": (21, false),
    "6": (22, false), "5": (23, false), "9": (25, false), "7": (26, false),
    "8": (28, false), "0": (29, false),
    // Punctuation & symbols
    "=": (24, false), "equals": (24, false),
    "-": (27, false), "minus": (27, false),
    "]": (30, false), "[": (33, false), "'": (39, false), ";": (41, false),
    "\\": (42, false), ",": (43, false), "/": (44, false), "slash": (44, false),
    ".": (47, false), "period": (47, false), "`": (50, false),
    "+": (24, true), "plus": (69, false),
    "*": (28, true), "multiply": (67, false),
    "%": (23, true), "(": (25, true), ")": (29, true),
    // Keypad keys
    "kp_decimal": (65, false), "kp_multiply": (67, false), "kp_plus": (69, false),
    "kp_clear": (71, false), "clear": (71, false), "kp_divide": (75, false),
    "divide": (75, false), "kp_enter": (76, false), "kp_minus": (78, false),
    "kp_equals": (81, false),
    "kp0": (82, false), "kp1": (83, false), "kp2": (84, false), "kp3": (85, false),
    "kp4": (86, false), "kp5": (87, false), "kp6": (88, false), "kp7": (89, false),
    "kp8": (91, false), "kp9": (92, false),
    // Control & navigation
    "return": (36, false), "enter": (36, false),
    "tab": (48, false),
    "space": (49, false),
    "delete": (51, false), "backspace": (51, false),
    "escape": (53, false), "esc": (53, false),
    "home": (115, false), "pageup": (116, false), "forwarddelete": (117, false),
    "end": (119, false), "pagedown": (121, false),
    "left": (123, false), "leftarrow": (123, false),
    "right": (124, false), "rightarrow": (124, false),
    "down": (125, false), "downarrow": (125, false),
    "up": (126, false), "uparrow": (126, false),
    // Function keys
    "f1": (122, false), "f2": (120, false), "f3": (99, false), "f4": (118, false),
    "f5": (96, false), "f6": (97, false), "f7": (98, false), "f8": (100, false),
    "f9": (101, false), "f10": (109, false), "f11": (103, false), "f12": (111, false),
]

func parseKeyCombo(_ raw: String) -> (keyCode: CGKeyCode, flags: CGEventFlags, label: String)? {
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    if trimmed == "+" {
        return (24, .maskShift, "+")
    }
    var working = trimmed
    var forcePlusKey = false
    if working.hasSuffix("++") {
        forcePlusKey = true
        working = String(working.dropLast(2))
    }
    var parts = working.split(separator: "+", omittingEmptySubsequences: false).map {
        String($0).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
    if forcePlusKey {
        parts.append("+")
    }
    guard let keyPart = parts.last, !keyPart.isEmpty, let mapped = universalMacKeyMap[keyPart] else {
        return nil
    }
    var eventFlags: CGEventFlags = mapped.1 ? .maskShift : []
    for mod in parts.dropLast() {
        switch mod {
        case "cmd", "command", "super", "meta":
            eventFlags.insert(.maskCommand)
        case "shift":
            eventFlags.insert(.maskShift)
        case "ctrl", "control":
            eventFlags.insert(.maskControl)
        case "opt", "option", "alt":
            eventFlags.insert(.maskAlternate)
        default:
            return nil
        }
    }
    return (mapped.0, eventFlags, trimmed)
}

func isUniversalHelperBundle(_ bid: String) -> Bool {
    let low = bid.lowercased()
    return low.contains("helper")
        || low.contains("renderer")
        || low.contains(".gpu")
        || low.contains("crashpad")
        || low.contains("webcontent")
        || low.contains("xpcservice")
}

func findRunningAppsGeneric(bundleID: String? = nil, appName: String? = nil, appPath: String? = nil) -> [NSRunningApplication] {
    let reqBID = (bundleID ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let reqName = (appName ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let reqPath = (appPath ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let frontPID = NSWorkspace.shared.frontmostApplication?.processIdentifier
    var matched: [NSRunningApplication] = []
    for app in NSWorkspace.shared.runningApplications where !app.isTerminated {
        let bid = (app.bundleIdentifier ?? "").lowercased()
        let name = (app.localizedName ?? "").lowercased()
        let path = app.bundleURL?.path ?? ""
        var ok = false
        if !reqBID.isEmpty && bid == reqBID {
            ok = true
        } else if !reqPath.isEmpty && !path.isEmpty && path == reqPath && !isUniversalHelperBundle(bid) {
            ok = true
        } else if reqBID.isEmpty && !reqName.isEmpty && !isUniversalHelperBundle(bid) {
            if name == reqName || bid == reqName || name.contains(reqName) {
                ok = true
            }
        }
        if ok {
            matched.append(app)
        }
    }
    matched.sort { lhs, rhs in
        let lr = lhs.activationPolicy == .regular
        let rr = rhs.activationPolicy == .regular
        if lr != rr { return lr && !rr }
        let lf = lhs.processIdentifier == frontPID
        let rf = rhs.processIdentifier == frontPID
        if lf != rf { return lf && !rf }
        let lnExact = !reqName.isEmpty && (lhs.localizedName ?? "").lowercased() == reqName
        let rnExact = !reqName.isEmpty && (rhs.localizedName ?? "").lowercased() == reqName
        if lnExact != rnExact { return lnExact && !rnExact }
        return lhs.processIdentifier < rhs.processIdentifier
    }
    return matched
}

func enableUniversalAccessibility(pid: pid_t) {
    guard AXIsProcessTrusted() else { return }
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 0.25)
    _ = AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    _ = AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
}

func listWindowsGeneric(for apps: [NSRunningApplication], rawWindowList: [[String: Any]]? = nil) -> [WindowCandidate] {
    guard !apps.isEmpty else { return [] }
    var appByPID: [pid_t: NSRunningApplication] = [:]
    for app in apps { appByPID[app.processIdentifier] = app }
    let rawList = rawWindowList ?? copyOnScreenWindowInfo()
    var seen = Set<CGWindowID>()
    var entries: [(wid: CGWindowID, pid: pid_t, bid: String, label: String, cgTitle: String, x: Double, y: Double, w: Double, h: Double)] = []
    for entry in rawList {
        guard let ownerPID = entry[kCGWindowOwnerPID as String] as? pid_t,
              let ownerApp = appByPID[ownerPID],
              (entry[kCGWindowLayer as String] as? Int) == 0,
              let num = entry[kCGWindowNumber as String] as? NSNumber,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              w >= 80, h >= 60 else { continue }
        let wid = num.uint32Value
        guard seen.insert(wid).inserted else { continue }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let cgTitle = ((entry[kCGWindowName as String] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        entries.append((wid, ownerPID, ownerApp.bundleIdentifier ?? "", ownerApp.localizedName ?? "", cgTitle, x, y, w, h))
    }
    guard !entries.isEmpty else { return [] }
    var axMetaByPID: [pid_t: [AXWindowMeta]] = [:]
    if AXIsProcessTrusted() && entries.contains(where: { $0.cgTitle.isEmpty }) {
        for pid in Set(entries.map { $0.pid }) {
            axMetaByPID[pid] = collectAXWindowMeta(pid: pid)
        }
    }
    var maxArea = 0.0
    var mainIdx = 0
    for (idx, item) in entries.enumerated() {
        let area = item.w * item.h
        if area > maxArea {
            maxArea = area
            mainIdx = idx
        }
    }
    var out: [WindowCandidate] = []
    for (idx, item) in entries.enumerated() {
        var resolvedTitle = item.cgTitle
        if resolvedTitle.isEmpty, let metas = axMetaByPID[item.pid] {
            let targetRect = CGRect(x: item.x, y: item.y, width: item.w, height: item.h)
            if let m = metas.min(by: {
                abs($0.frame.origin.x - targetRect.origin.x) + abs($0.frame.origin.y - targetRect.origin.y)
                    < abs($1.frame.origin.x - targetRect.origin.x) + abs($1.frame.origin.y - targetRect.origin.y)
            }), !m.title.isEmpty {
                resolvedTitle = m.title
            }
        }
        if resolvedTitle.isEmpty && idx == mainIdx {
            resolvedTitle = item.label
        }
        out.append(WindowCandidate(
            windowID: item.wid,
            appId: item.bid,
            appLabel: item.label,
            bundleID: item.bid,
            pid: item.pid,
            title: resolvedTitle,
            isMainWindow: idx == mainIdx,
            x: item.x, y: item.y, width: item.w, height: item.h
        ))
    }
    out.sort { lhs, rhs in
        if lhs.isMainWindow != rhs.isMainWindow { return lhs.isMainWindow && !rhs.isMainWindow }
        if lhs.area != rhs.area { return lhs.area > rhs.area }
        return lhs.windowID < rhs.windowID
    }
    return out
}

func launchGenericApp(bundleID: String?, appPath: String?, appName: String?) -> NSRunningApplication? {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    if let p = appPath?.trimmingCharacters(in: .whitespacesAndNewlines), !p.isEmpty,
       FileManager.default.fileExists(atPath: p) {
        proc.arguments = [p]
    } else if let b = bundleID?.trimmingCharacters(in: .whitespacesAndNewlines), !b.isEmpty {
        proc.arguments = ["-b", b]
    } else if let n = appName?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty {
        proc.arguments = ["-a", n]
    } else {
        return nil
    }
    proc.standardOutput = FileHandle.nullDevice
    proc.standardError = FileHandle.nullDevice
    do {
        try proc.run()
        proc.waitUntilExit()
    } catch {
        return nil
    }
    for _ in 0..<18 {
        usleep(220_000)
        let running = findRunningAppsGeneric(bundleID: bundleID, appName: appName, appPath: appPath)
        if let app = running.first {
            return app
        }
    }
    return findRunningAppsGeneric(bundleID: bundleID, appName: appName, appPath: appPath).first
}

func resolveGenericAppAndWindows(options: [String: String], allowLaunch: Bool, allowActivate: Bool) -> (app: NSRunningApplication?, windows: [WindowCandidate], recovery: String?) {
    let bid = options["bundle-id"]
    let appName = options["app-name"]
    let appPath = options["app-path"]
    var recovery: String? = nil

    var apps = findRunningAppsGeneric(bundleID: bid, appName: appName, appPath: appPath)
    if apps.isEmpty && allowLaunch {
        if launchGenericApp(bundleID: bid, appPath: appPath, appName: appName) != nil {
            recovery = "launched"
            apps = findRunningAppsGeneric(bundleID: bid, appName: appName, appPath: appPath)
        }
    }
    guard let primaryApp = apps.first else {
        return (nil, [], recovery)
    }

    var windows = listWindowsGeneric(for: apps)
    if windows.isEmpty && allowActivate {
        _ = primaryApp.unhide()
        _ = primaryApp.activate(options: [.activateIgnoringOtherApps])
        usleep(220_000)
        if AXIsProcessTrusted() {
            let axApp = AXUIElementCreateApplication(primaryApp.processIdentifier)
            if let axWins = axAttr(axApp, kAXWindowsAttribute) as? [AXUIElement] {
                for w in axWins {
                    if axBool(w, kAXMinimizedAttribute) == true {
                        _ = AXUIElementSetAttributeValue(w, kAXMinimizedAttribute as CFString, kCFBooleanFalse)
                        recovery = recovery ?? "ax_unminimize"
                    }
                    _ = AXUIElementPerformAction(w, kAXRaiseAction as CFString)
                }
                usleep(250_000)
            }
        }
        windows = listWindowsGeneric(for: apps)
        if windows.isEmpty {
            _ = launchGenericApp(bundleID: primaryApp.bundleIdentifier ?? bid, appPath: primaryApp.bundleURL?.path ?? appPath, appName: primaryApp.localizedName ?? appName)
            usleep(300_000)
            apps = findRunningAppsGeneric(bundleID: bid, appName: appName, appPath: appPath)
            windows = listWindowsGeneric(for: apps)
            if !windows.isEmpty { recovery = recovery ?? "reopen" }
        }
    }
    return (apps.first ?? primaryApp, windows, recovery)
}

func findGenericAXWindow(pid: pid_t, targetWin: WindowCandidate?, reqTitle: String?) -> AXUIElement? {
    guard AXIsProcessTrusted() else { return nil }
    let effectivePID = targetWin?.pid ?? pid
    enableUniversalAccessibility(pid: effectivePID)
    let app = AXUIElementCreateApplication(effectivePID)
    AXUIElementSetMessagingTimeout(app, 0.30)
    guard let windows = axAttr(app, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else {
        return nil
    }
    if let tw = targetWin {
        var best: AXUIElement?
        var bestDist = Double.greatestFiniteMagnitude
        for win in windows {
            if let pt = axPoint(win, kAXPositionAttribute), let sz = axSize(win, kAXSizeAttribute) {
                let d = abs(Double(pt.x) - tw.x) + abs(Double(pt.y) - tw.y)
                    + abs(Double(sz.width) - tw.width) + abs(Double(sz.height) - tw.height)
                if d < bestDist {
                    bestDist = d
                    best = win
                }
            }
        }
        if best != nil && bestDist <= 36.0 {
            return best
        }
        let twTitle = tw.title.lowercased()
        if !twTitle.isEmpty,
           let byTitle = windows.first(where: { (axString($0, kAXTitleAttribute) ?? "").lowercased() == twTitle }) {
            return byTitle
        }
    }
    if let t = reqTitle?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty {
        let low = t.lowercased()
        if let m = windows.first(where: { (axString($0, kAXTitleAttribute) ?? "").lowercased().contains(low) }) {
            return m
        }
    }
    return windows.max(by: { lhs, rhs in
        let lsz = axSize(lhs, kAXSizeAttribute) ?? .zero
        let rsz = axSize(rhs, kAXSizeAttribute) ?? .zero
        return (lsz.width * lsz.height) < (rsz.width * rsz.height)
    })
}

func installSourceTag(for path: String) -> String {
    if path.hasPrefix("/Volumes/SanDisk/Applications") { return "sandisk" }
    if path.hasPrefix("/System/Applications") { return "system" }
    if path.hasPrefix("/Users/mac/Applications") { return "user_applications" }
    if path.hasPrefix("/Applications") { return "applications" }
    return "other"
}

func cmdListMacApps(flags: Set<String>, options: [String: String]) {
    let rawList = copyOnScreenWindowInfo()
    let frontApp = NSWorkspace.shared.frontmostApplication
    let runningOnly = flags.contains("running-only")

    var winCountByPID: [pid_t: Int] = [:]
    var sampleWinByPID: [pid_t: WindowCandidate] = [:]
    for entry in rawList {
        guard let pid = entry[kCGWindowOwnerPID as String] as? pid_t,
              (entry[kCGWindowLayer as String] as? Int) == 0,
              let num = entry[kCGWindowNumber as String] as? NSNumber,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              w >= 80, h >= 60 else { continue }
        winCountByPID[pid, default: 0] += 1
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let title = ((entry[kCGWindowName as String] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let cand = WindowCandidate(
            windowID: num.uint32Value, appId: "", appLabel: "", bundleID: "", pid: pid,
            title: title, isMainWindow: false, x: x, y: y, width: w, height: h
        )
        if let cur = sampleWinByPID[pid] {
            if cand.area > cur.area { sampleWinByPID[pid] = cand }
        } else {
            sampleWinByPID[pid] = cand
        }
    }

    var byKey: [String: [String: Any]] = [:]
    var seenKeys: [String] = []
    var runningCount = 0

    for app in NSWorkspace.shared.runningApplications where !app.isTerminated && app.activationPolicy == .regular {
        let bid = app.bundleIdentifier ?? ""
        let path = app.bundleURL?.path ?? ""
        let key = (!bid.isEmpty ? bid : path).lowercased()
        guard !key.isEmpty else { continue }
        let name = app.localizedName ?? (URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent)
        let pid = app.processIdentifier
        let isFront = (frontApp?.processIdentifier == pid)
        let wCount = winCountByPID[pid] ?? 0
        runningCount += 1
        var item: [String: Any] = [
            "bundleID": bid,
            "name": name,
            "pid": Int(pid),
            "running": true,
            "isFrontmost": isFront,
            "appPath": path,
            "windowCount": wCount,
            "installSource": installSourceTag(for: path),
        ]
        if let sw = sampleWinByPID[pid] {
            let mainWinDict: [String: Any] = [
                "windowID": sw.windowID,
                "title": sw.title.isEmpty ? name : sw.title,
                "bounds": ["x": sw.x, "y": sw.y, "width": sw.width, "height": sw.height],
            ]
            item["mainWindow"] = mainWinDict
        }
        if byKey[key] == nil { seenKeys.append(key) }
        if let existing = byKey[key], (existing["windowCount"] as? Int ?? 0) > wCount && !isFront {
            continue
        }
        byKey[key] = item
    }

    if !runningOnly {
        var scanDirs = [
            "/Applications",
            "/System/Applications",
            "/System/Applications/Utilities",
            "/Users/mac/Applications",
            "/Volumes/SanDisk/Applications",
        ]
        let homeApps = (NSHomeDirectory() as NSString).appendingPathComponent("Applications")
        if !scanDirs.contains(homeApps) { scanDirs.append(homeApps) }

        let fm = FileManager.default
        for dir in scanDirs {
            guard let items = try? fm.contentsOfDirectory(atPath: dir) else { continue }
            for entry in items where entry.hasSuffix(".app") {
                let fullPath = (dir as NSString).appendingPathComponent(entry)
                let url = URL(fileURLWithPath: fullPath)
                let bundle = Bundle(url: url)
                let bid = bundle?.bundleIdentifier ?? ""
                let info = bundle?.infoDictionary
                let dispName = (info?["CFBundleDisplayName"] as? String)
                    ?? (info?["CFBundleName"] as? String)
                    ?? url.deletingPathExtension().lastPathComponent
                let key = (!bid.isEmpty ? bid : fullPath).lowercased()
                guard !key.isEmpty else { continue }
                if byKey[key] == nil {
                    seenKeys.append(key)
                    byKey[key] = [
                        "bundleID": bid,
                        "name": dispName,
                        "pid": NSNull(),
                        "running": false,
                        "isFrontmost": false,
                        "appPath": fullPath,
                        "windowCount": 0,
                        "installSource": installSourceTag(for: fullPath),
                    ]
                }
            }
        }
    }

    let merged = seenKeys.compactMap { byKey[$0] }.sorted { a, b in
        let ar = (a["running"] as? Bool) ?? false
        let br = (b["running"] as? Bool) ?? false
        if ar != br { return ar && !br }
        let af = (a["isFrontmost"] as? Bool) ?? false
        let bf = (b["isFrontmost"] as? Bool) ?? false
        if af != bf { return af && !bf }
        let aw = (a["windowCount"] as? Int) ?? 0
        let bw = (b["windowCount"] as? Int) ?? 0
        if (aw > 0) != (bw > 0) { return aw > 0 }
        return ((a["name"] as? String) ?? "").lowercased() < ((b["name"] as? String) ?? "").lowercased()
    }

    writeJSON([
        "ok": true,
        "frontmostBundleID": frontApp?.bundleIdentifier ?? "",
        "frontmostName": frontApp?.localizedName ?? "",
        "runningCount": runningCount,
        "totalCount": merged.count,
        "apps": merged,
    ])
}

func queryLiveFrontmostApp() -> (pid: pid_t, bundleID: String, name: String) {
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.015))
    let sysWide = AXUIElementCreateSystemWide()
    AXUIElementSetMessagingTimeout(sysWide, 0.2)
    if let raw = axAttr(sysWide, kAXFocusedApplicationAttribute), CFGetTypeID(raw) == AXUIElementGetTypeID() {
        let focusedAX = raw as! AXUIElement
        var axPid: pid_t = 0
        if AXUIElementGetPid(focusedAX, &axPid) == .success, axPid > 0 {
            if let r = NSRunningApplication(processIdentifier: axPid) {
                return (axPid, r.bundleIdentifier ?? "", r.localizedName ?? "")
            }
            return (axPid, "", "")
        }
    }
    if let ws = NSWorkspace.shared.frontmostApplication {
        return (ws.processIdentifier, ws.bundleIdentifier ?? "", ws.localizedName ?? "")
    }
    return (0, "", "")
}

@discardableResult
func activateTargetAppReliably(_ app: NSRunningApplication, targetWin: WindowCandidate?, reqTitle: String? = nil) -> Bool {
    let targetPid = targetWin?.pid ?? app.processIdentifier
    let targetBID = (app.bundleIdentifier ?? "").lowercased()
    func matchesFront() -> Bool {
        let f = queryLiveFrontmostApp()
        return f.pid == app.processIdentifier
            || f.pid == targetPid
            || (!targetBID.isEmpty && f.bundleID.lowercased() == targetBID)
    }

    let axApp = AXUIElementCreateApplication(targetPid)
    AXUIElementSetMessagingTimeout(axApp, 0.3)
    _ = app.unhide()
    _ = app.activate(options: [.activateIgnoringOtherApps])
    _ = AXUIElementSetAttributeValue(axApp, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
    if let axWin = findGenericAXWindow(pid: targetPid, targetWin: targetWin, reqTitle: reqTitle) {
        _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
    }
    for _ in 0..<10 {
        if matchesFront() { return true }
        usleep(50_000)
    }
    if let bid = app.bundleIdentifier, !bid.isEmpty {
        let openProc = Process()
        openProc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        openProc.arguments = ["-b", bid]
        openProc.standardOutput = FileHandle.nullDevice
        openProc.standardError = FileHandle.nullDevice
        try? openProc.run()
        openProc.waitUntilExit()
        _ = AXUIElementSetAttributeValue(axApp, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
        if let axWin = findGenericAXWindow(pid: targetPid, targetWin: targetWin, reqTitle: reqTitle) {
            _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
            _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
        }
        for _ in 0..<8 {
            if matchesFront() { return true }
            usleep(50_000)
        }
    }
    return matchesFront()
}

func cmdAppUseActivate(flags: Set<String>, options: [String: String]) {
    let allowLaunch = flags.contains("launch") || options["launch"] == "1"
    let (resolvedApp, windows, recovery) = resolveGenericAppAndWindows(options: options, allowLaunch: allowLaunch, allowActivate: true)
    guard let app = resolvedApp else {
        failJSON("Target app is not running (pass --launch to open it).", code: "app_not_running")
    }
    let targetWin = selectTargetWindow(in: windows, options: options)
    let isFront = activateTargetAppReliably(app, targetWin: targetWin, reqTitle: options["window-title"])
    var resp: [String: Any] = [
        "ok": true,
        "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
        "name": app.localizedName ?? (options["app-name"] ?? ""),
        "pid": Int(app.processIdentifier),
        "appPath": app.bundleURL?.path ?? "",
        "isFrontmost": isFront,
        "windowCount": windows.count,
        "windows": windows.map { $0.toDict() },
    ]
    if let r = recovery { resp["recovery"] = r }
    writeJSON(resp)
}

func cmdAppUseInspect(flags: Set<String>, options: [String: String]) {
    let allowLaunch = flags.contains("launch") || options["launch"] == "1"
    let allowActivate = !flags.contains("no-activate")
    let skipOCR = flags.contains("skip-ocr")
    let maxNodes = max(40, min(800, Int(options["max-nodes"] ?? "350") ?? 350))
    let maxDepth = max(3, min(18, Int(options["max-depth"] ?? "10") ?? 10))

    var (resolvedApp, windows, recovery) = resolveGenericAppAndWindows(options: options, allowLaunch: allowLaunch, allowActivate: allowActivate)
    guard let app = resolvedApp else {
        failJSON("Target app is not running (pass --launch to start it).", code: "app_not_running")
    }

    let pid = app.processIdentifier
    enableUniversalAccessibility(pid: pid)
    if allowActivate {
        _ = app.unhide()
        _ = app.activate(options: [.activateIgnoringOtherApps])
        usleep(220_000)
        if windows.isEmpty {
            windows = listWindowsGeneric(for: findRunningAppsGeneric(
                bundleID: app.bundleIdentifier ?? options["bundle-id"],
                appName: app.localizedName ?? options["app-name"],
                appPath: app.bundleURL?.path ?? options["app-path"]
            ))
        }
    }

    let targetWin = selectTargetWindow(in: windows, options: options)
    var axControls: [[String: Any]] = []
    var inputElements: [[String: Any]] = []
    var buttonElements: [[String: Any]] = []
    var axTexts: [String] = []
    var seenTexts = Set<String>()

    let interestingRoles: Set<String> = [
        kAXButtonRole as String,
        kAXTextFieldRole as String,
        kAXTextAreaRole as String,
        "AXSearchField",
        kAXComboBoxRole as String,
        kAXPopUpButtonRole as String,
        kAXCheckBoxRole as String,
        kAXRadioButtonRole as String,
        "AXTab",
        kAXMenuButtonRole as String,
        "AXLink",
        kAXStaticTextRole as String,
        "AXWebArea",
    ]
    let inputRoles: Set<String> = [kAXTextAreaRole as String, kAXTextFieldRole as String, "AXSearchField", kAXComboBoxRole as String]
    let buttonRoles: Set<String> = [kAXButtonRole as String, kAXRadioButtonRole as String, kAXCheckBoxRole as String, kAXMenuButtonRole as String, kAXPopUpButtonRole as String, "AXTab"]

    let effPID = targetWin?.pid ?? pid
    if AXIsProcessTrusted(), let axRoot = findGenericAXWindow(pid: effPID, targetWin: targetWin, reqTitle: options["window-title"]) {
        var queue: [(AXUIElement, Int)] = [(axRoot, 0)]
        var qi = 0
        let deadline = CFAbsoluteTimeGetCurrent() + 2.2
        while qi < queue.count && axControls.count < maxNodes && qi < 1800 && CFAbsoluteTimeGetCurrent() < deadline {
            let (el, depth) = queue[qi]; qi += 1
            let role = axString(el, kAXRoleAttribute) ?? ""
            let subrole = axString(el, kAXSubroleAttribute) ?? ""
            let ident = axString(el, kAXIdentifierAttribute) ?? ""
            let title = axString(el, kAXTitleAttribute) ?? ""
            let desc = axString(el, kAXDescriptionAttribute) ?? ""
            let rawVal = axString(el, kAXValueAttribute) ?? ""
            let val = rawVal.count > 240 ? String(rawVal.prefix(240)) : rawVal
            let focused = axBool(el, kAXFocusedAttribute) ?? false
            let enabled = axBool(el, kAXEnabledAttribute) ?? true
            let pt = axPoint(el, kAXPositionAttribute)
            let sz = axSize(el, kAXSizeAttribute)

            let hasLabel = !ident.isEmpty || !title.isEmpty || !desc.isEmpty || !val.isEmpty
            if interestingRoles.contains(role) || (depth > 0 && hasLabel && sz != nil) {
                var ctrl: [String: Any] = [
                    "depth": depth,
                    "role": role,
                    "focused": focused,
                    "enabled": enabled,
                ]
                if !subrole.isEmpty { ctrl["subrole"] = subrole }
                if !ident.isEmpty { ctrl["identifier"] = ident }
                if !title.isEmpty { ctrl["title"] = title }
                if !desc.isEmpty { ctrl["description"] = desc }
                if !val.isEmpty { ctrl["value"] = val }
                if let pt = pt, let sz = sz, sz.width > 1, sz.height > 1 {
                    let cx = Double(pt.x) + Double(sz.width) / 2.0
                    let cy = Double(pt.y) + Double(sz.height) / 2.0
                    ctrl["bounds"] = ["x": Double(pt.x), "y": Double(pt.y), "width": Double(sz.width), "height": Double(sz.height)]
                    ctrl["center"] = ["x": (cx * 10.0).rounded() / 10.0, "y": (cy * 10.0).rounded() / 10.0]
                    if let tw = targetWin, tw.width > 1, tw.height > 1 {
                        let rx = (cx - tw.x) / tw.width
                        let ry = (cy - tw.y) / tw.height
                        ctrl["relCenter"] = ["x": (rx * 1000.0).rounded() / 1000.0, "y": (ry * 1000.0).rounded() / 1000.0]
                    }
                }
                if interestingRoles.contains(role) || inputRoles.contains(role) || buttonRoles.contains(role) || !ident.isEmpty {
                    axControls.append(ctrl)
                    if inputRoles.contains(role) || inputIdentifiers.contains(ident) {
                        inputElements.append(ctrl)
                    } else if buttonRoles.contains(role) {
                        buttonElements.append(ctrl)
                    }
                }
                if role == (kAXStaticTextRole as String) || inputRoles.contains(role) {
                    let txt = !val.isEmpty ? val : title
                    if !txt.isEmpty && seenTexts.insert(txt).inserted && axTexts.count < 50 {
                        axTexts.append(txt)
                    }
                }
            }
            if depth < maxDepth {
                for child in axChildren(el) {
                    queue.append((child, depth + 1))
                }
            }
        }
    }

    var ocrElements: [[String: Any]] = []
    var ocrPreview = ""
    var savedPath: String? = nil
    var imageWidth = 0
    var imageHeight = 0
    var windowOccluded = false

    if !skipOCR, CGPreflightScreenCaptureAccess(), let win = targetWin {
        var cgImage = captureWindowImage(win)
        if let img = cgImage, isImageFullyTransparent(img), allowActivate {
            _ = app.activate(options: [.activateIgnoringOtherApps])
            usleep(260_000)
            cgImage = captureWindowImage(win)
        }
        if let img = cgImage {
            if isImageFullyTransparent(img) {
                windowOccluded = true
            } else {
                imageWidth = img.width
                imageHeight = img.height
                if let outPath = options["out"], !outPath.isEmpty {
                    let parent = URL(fileURLWithPath: outPath).deletingLastPathComponent()
                    try? FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
                    if saveCGImageAsPNG(img, to: outPath) {
                        savedPath = outPath
                    }
                }
                if let rawOCR = try? runVisionOCR(cgImage: img) {
                    let sx = max(0.1, Double(img.width) / max(win.width, 1.0))
                    let sy = max(0.1, Double(img.height) / max(win.height, 1.0))
                    ocrElements = rawOCR.map { item in
                        var copy = item
                        if let c = item["center"] as? [String: Int], let px = c["x"], let py = c["y"] {
                            let scrX = win.x + Double(px) / sx
                            let scrY = win.y + Double(py) / sy
                            copy["screenCenter"] = ["x": (scrX * 10.0).rounded() / 10.0, "y": (scrY * 10.0).rounded() / 10.0]
                            copy["relCenter"] = [
                                "x": ((scrX - win.x) / max(win.width, 1.0) * 1000.0).rounded() / 1000.0,
                                "y": ((scrY - win.y) / max(win.height, 1.0) * 1000.0).rounded() / 1000.0,
                            ]
                        }
                        return copy
                    }
                    ocrPreview = ocrElements.compactMap { $0["text"] as? String }.prefix(80).joined(separator: "\n")
                }
            }
        }
    }

    var resp: [String: Any] = [
        "ok": true,
        "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
        "name": app.localizedName ?? (options["app-name"] ?? ""),
        "pid": Int(pid),
        "appPath": app.bundleURL?.path ?? "",
        "axTrusted": AXIsProcessTrusted(),
        "scTrusted": CGPreflightScreenCaptureAccess(),
        "postEventTrusted": CGPreflightPostEventAccess(),
        "windowCount": windows.count,
        "windows": windows.map { $0.toDict() },
        "window": targetWin?.toDict() as Any,
        "windowOccluded": windowOccluded,
        "imageWidth": imageWidth,
        "imageHeight": imageHeight,
        "axControlCount": axControls.count,
        "axControls": axControls,
        "inputElements": inputElements,
        "buttonElements": buttonElements,
        "axTexts": axTexts,
        "ocrCount": ocrElements.count,
        "ocrElements": ocrElements,
        "ocrPreview": ocrPreview,
    ]
    if let s = savedPath { resp["savedPath"] = s }
    if let r = recovery { resp["recovery"] = r }
    writeJSON(resp)
}

func cmdPressKey(flags: Set<String>, options: [String: String]) {
    guard CGPreflightPostEventAccess() else {
        failJSON("macOS Accessibility/PostEvent permission (CGPreflightPostEventAccess) is not granted.", code: "post_event_permission_denied")
    }
    let hasAppTarget = !(options["bundle-id"] ?? "").isEmpty || !(options["app-name"] ?? "").isEmpty || !(options["app-path"] ?? "").isEmpty
    var targetApp: NSRunningApplication? = nil
    if hasAppTarget {
        let allowLaunch = flags.contains("launch") || options["launch"] == "1"
        let allowActivate = !flags.contains("no-activate")
        let (app, windows, _) = resolveGenericAppAndWindows(options: options, allowLaunch: allowLaunch, allowActivate: allowActivate)
        guard let app = app else {
            failJSON("Target app not running.", code: "app_not_running")
        }
        targetApp = app
        if allowActivate {
            let targetWin = selectTargetWindow(in: windows, options: options)
            _ = activateTargetAppReliably(app, targetWin: targetWin, reqTitle: options["window-title"])
        }
    }

    var rawList: [String] = []
    if let seq = options["sequence"], !seq.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        rawList = seq.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    } else if let combo = options["combo"], !combo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        let repeatCount = max(1, min(20, Int(options["repeat"] ?? "1") ?? 1))
        rawList = Array(repeating: combo, count: repeatCount)
    } else {
        failJSON("Missing --combo or --sequence argument.", code: "missing_argument")
    }

    var parsedCombos: [(keyCode: CGKeyCode, flags: CGEventFlags, label: String)] = []
    for item in rawList {
        guard let pc = parseKeyCombo(item) else {
            failJSON("Unsupported key or combo: '\(item)'", code: "invalid_key_combo")
        }
        parsedCombos.append(pc)
    }

    let delayMs = max(20, min(1500, Int(options["delay-ms"] ?? "85") ?? 85))
    var postedLabels: [String] = []
    for (idx, item) in parsedCombos.enumerated() {
        postKey(keyCode: item.keyCode, flags: item.flags)
        postedLabels.append(item.label)
        if idx < parsedCombos.count - 1 {
            usleep(useconds_t(delayMs * 1000))
        }
    }
    let front = queryLiveFrontmostApp()
    writeJSON([
        "ok": true,
        "posted": postedLabels,
        "count": postedLabels.count,
        "targetBundleID": targetApp?.bundleIdentifier ?? "",
        "frontmostBundleID": front.bundleID,
        "frontmostName": front.name,
    ])
}

func cmdAppUsePaste(flags: Set<String>, options: [String: String]) {
    guard AXIsProcessTrusted(), CGPreflightPostEventAccess() else {
        failJSON("Accessibility/PostEvent permissions are required.", code: "ax_permission_denied")
    }
    guard let text = options["text"] else {
        failJSON("Missing --text argument", code: "missing_argument")
    }
    let allowLaunch = flags.contains("launch") || options["launch"] == "1"
    let (resolvedApp, windows, _) = resolveGenericAppAndWindows(options: options, allowLaunch: allowLaunch, allowActivate: true)
    guard let app = resolvedApp else {
        failJSON("Target app is not running.", code: "app_not_running")
    }
    let targetWin = selectTargetWindow(in: windows, options: options)
    let targetBID = (app.bundleIdentifier ?? "").lowercased()
    let isFront = activateTargetAppReliably(app, targetWin: targetWin, reqTitle: options["window-title"])
    if !isFront {
        let front = queryLiveFrontmostApp()
        failJSON("Aborted: frontmost app is '\(front.name) (\(front.bundleID.lowercased()))', expected \(app.localizedName ?? targetBID).", code: "not_frontmost")
    }

    if !flags.contains("skip-human-check") && hardwareKeyboardIdleSeconds() < 1.8 {
        failJSON("Human keyboard activity detected; paused safely.", code: "human_keyboard_active", extra: ["retryable": true])
    }

    var clickX = options["x"].flatMap { Double($0) }
    var clickY = options["y"].flatMap { Double($0) }
    if (clickX == nil || clickY == nil), let win = targetWin,
       let rx = options["rel-x"].flatMap({ Double($0) }),
       let ry = options["rel-y"].flatMap({ Double($0) }) {
        clickX = win.x + rx * win.width
        clickY = win.y + ry * win.height
    }

    var axInputEl: AXUIElement? = nil
    if let axWin = findGenericAXWindow(pid: targetWin?.pid ?? app.processIdentifier, targetWin: targetWin, reqTitle: options["window-title"]) {
        _ = AXUIElementSetAttributeValue(axWin, kAXMainAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementPerformAction(axWin, kAXRaiseAction as CFString)
        axInputEl = findInputElement(in: axWin, windowBounds: targetWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) })
        if clickX == nil || clickY == nil, let el = axInputEl,
           let pt = axPoint(el, kAXPositionAttribute), let sz = axSize(el, kAXSizeAttribute),
           sz.width > 10, sz.height > 10 {
            clickX = Double(pt.x) + Double(sz.width) / 2.0
            clickY = Double(pt.y) + Double(sz.height) / 2.0
        }
    }

    if !flags.contains("no-click"), let cx = clickX, let cy = clickY {
        moveAndClick(x: cx, y: cy)
        usleep(160_000)
    } else if let el = axInputEl {
        _ = AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        usleep(120_000)
    }

    let pb = NSPasteboard.general
    let originalClipboard = pb.string(forType: .string)
    func restoreClipboard() {
        pb.clearContents()
        if let orig = originalClipboard { pb.setString(orig, forType: .string) }
    }

    if flags.contains("clear") || options["clear"] == "1" {
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete, flags: [])
        usleep(80_000)
    }

    pb.clearContents()
    pb.setString(text, forType: .string)
    postKey(keyCode: kKeyV, flags: .maskCommand)
    usleep(240_000)

    var readback = ""
    var readbackSource = "ax"
    let axApp = AXUIElementCreateApplication(targetWin?.pid ?? app.processIdentifier)
    if let focusedRaw = axAttr(axApp, kAXFocusedUIElementAttribute) {
        let focusedEl = focusedRaw as! AXUIElement
        if let v = axString(focusedEl, kAXValueAttribute), !v.isEmpty {
            readback = v
        }
    }
    if readback.isEmpty, let el = axInputEl, let v = axString(el, kAXValueAttribute), !v.isEmpty {
        readback = v
    }
    if readback.isEmpty, CGPreflightScreenCaptureAccess(), let win = targetWin, let img = captureWindowImage(win),
       let items = try? runVisionOCR(cgImage: img) {
        readback = items.compactMap { $0["text"] as? String }.joined(separator: " ")
        readbackSource = "vision_ocr"
    }

    let stripWS: (String) -> String = { s in
        String(s.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) })
    }
    let expectedStripped = stripWS(text)
    let verified = expectedStripped.isEmpty ? true : stripWS(readback).contains(expectedStripped)

    var submitted = false
    let wantSubmit = (flags.contains("submit") || options["submit"] == "1") && !flags.contains("silent")
    if wantSubmit {
        let submitKeyName = options["submit-key"] ?? "return"
        if let sk = parseKeyCombo(submitKeyName) {
            postKey(keyCode: sk.keyCode, flags: sk.flags)
            usleep(220_000)
            submitted = true
        }
    }

    restoreClipboard()
    var resp: [String: Any] = [
        "ok": verified || !text.isEmpty,
        "verified": verified,
        "submitted": submitted,
        "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
        "name": app.localizedName ?? (options["app-name"] ?? ""),
        "readbackSource": readbackSource,
        "readbackPreview": readback.count > 260 ? String(readback.prefix(260)) : readback,
    ]
    if let w = targetWin {
        resp["windowID"] = w.windowID
        resp["windowTitle"] = w.title
    }
    if let cx = clickX, let cy = clickY {
        resp["clickPoint"] = ["x": cx, "y": cy]
    }
    writeJSON(resp)
}

func serializeAXElementBrief(_ el: AXUIElement, windowBounds: CGRect?) -> [String: Any] {
    var out: [String: Any] = [:]
    let role = axString(el, kAXRoleAttribute) ?? ""
    let subrole = axString(el, kAXSubroleAttribute) ?? ""
    let ident = axString(el, kAXIdentifierAttribute) ?? ""
    let title = axString(el, kAXTitleAttribute) ?? ""
    let desc = axString(el, kAXDescriptionAttribute) ?? ""
    let rawVal = axString(el, kAXValueAttribute) ?? ""
    let val = rawVal.count > 240 ? String(rawVal.prefix(240)) : rawVal
    if !role.isEmpty { out["role"] = role }
    if !subrole.isEmpty { out["subrole"] = subrole }
    if !ident.isEmpty { out["identifier"] = ident }
    if !title.isEmpty { out["title"] = title }
    if !desc.isEmpty { out["description"] = desc }
    if !val.isEmpty { out["value"] = val }
    if let pt = axPoint(el, kAXPositionAttribute), let sz = axSize(el, kAXSizeAttribute), sz.width > 1, sz.height > 1 {
        let cx = Double(pt.x) + Double(sz.width) / 2.0
        let cy = Double(pt.y) + Double(sz.height) / 2.0
        out["bounds"] = ["x": Double(pt.x), "y": Double(pt.y), "width": Double(sz.width), "height": Double(sz.height)]
        out["center"] = ["x": (cx * 10.0).rounded() / 10.0, "y": (cy * 10.0).rounded() / 10.0]
        if let wb = windowBounds, wb.width > 1, wb.height > 1 {
            out["relCenter"] = [
                "x": ((cx - Double(wb.minX)) / Double(wb.width) * 1000.0).rounded() / 1000.0,
                "y": ((cy - Double(wb.minY)) / Double(wb.height) * 1000.0).rounded() / 1000.0,
            ]
        }
    }
    return out
}

func findBestMatchingAXElement(
    in root: AXUIElement,
    windowBounds: CGRect?,
    options: [String: String],
    preferEditable: Bool
) -> (element: AXUIElement, score: Double, brief: [String: Any])? {
    let maxNodes = max(40, min(600, Int(options["max-nodes"] ?? "350") ?? 350))
    let reqIdent = (options["identifier"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let reqTitle = (options["title"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let reqRole = (options["role"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)

    var targetX = options["x"].flatMap { Double($0) }
    var targetY = options["y"].flatMap { Double($0) }
    if (targetX == nil || targetY == nil), let wb = windowBounds,
       let rx = options["rel-x"].flatMap({ Double($0) }),
       let ry = options["rel-y"].flatMap({ Double($0) }) {
        targetX = Double(wb.minX) + rx * Double(wb.width)
        targetY = Double(wb.minY) + ry * Double(wb.height)
    }

    let editableRoles: Set<String> = [
        kAXTextAreaRole as String,
        kAXTextFieldRole as String,
        "AXSearchField",
        kAXComboBoxRole as String,
    ]
    let hasSelector = !reqIdent.isEmpty || !reqTitle.isEmpty || !reqRole.isEmpty || (targetX != nil && targetY != nil)

    var queue: [(AXUIElement, Int)] = [(root, 0)]
    var qi = 0
    var visited = 0
    let deadline = CFAbsoluteTimeGetCurrent() + 1.8
    var bestEl: AXUIElement?
    var bestScore = -1.0
    var bestBrief: [String: Any] = [:]

    while qi < queue.count && visited < maxNodes && qi < 1800 && CFAbsoluteTimeGetCurrent() < deadline {
        let (el, depth) = queue[qi]; qi += 1
        visited += 1

        let role = axString(el, kAXRoleAttribute) ?? ""
        let ident = axString(el, kAXIdentifierAttribute) ?? ""
        let title = axString(el, kAXTitleAttribute) ?? ""
        let desc = axString(el, kAXDescriptionAttribute) ?? ""
        let rawVal = axString(el, kAXValueAttribute) ?? ""
        let enabled = axBool(el, kAXEnabledAttribute) ?? true

        if enabled && depth > 0 {
            var score = 0.0
            if !reqIdent.isEmpty {
                if ident == reqIdent {
                    score += 100.0
                } else if !ident.isEmpty && ident.lowercased() == reqIdent.lowercased() {
                    score += 90.0
                }
            }
            if !reqTitle.isEmpty {
                let candidates = [title.lowercased(), desc.lowercased()]
                    + (!preferEditable && !rawVal.isEmpty && rawVal.count <= 60 ? [rawVal.lowercased()] : [])
                if candidates.contains(where: { !$0.isEmpty && $0 == reqTitle }) {
                    score += 70.0
                } else if candidates.contains(where: { !$0.isEmpty && $0.contains(reqTitle) }) {
                    score += 35.0
                }
            }
            if !reqRole.isEmpty && role == reqRole {
                score += 25.0
            }
            if preferEditable && editableRoles.contains(role) {
                score += 30.0
            }
            if let tx = targetX, let ty = targetY,
               let pt = axPoint(el, kAXPositionAttribute),
               let sz = axSize(el, kAXSizeAttribute),
               sz.width > 1, sz.height > 1 {
                let inBounds = tx >= Double(pt.x) - 4.0 && tx <= Double(pt.x + sz.width) + 4.0
                    && ty >= Double(pt.y) - 4.0 && ty <= Double(pt.y + sz.height) + 4.0
                if inBounds {
                    score += 45.0
                } else {
                    let cx = Double(pt.x) + Double(sz.width) / 2.0
                    let cy = Double(pt.y) + Double(sz.height) / 2.0
                    let dist = hypot(cx - tx, cy - ty)
                    if dist <= 40.0 {
                        score += 40.0
                    } else if dist <= 120.0 {
                        score += 18.0
                    }
                }
            }

            if score >= 25.0 && score > bestScore {
                bestScore = score
                bestEl = el
                bestBrief = serializeAXElementBrief(el, windowBounds: windowBounds)
            }
        }

        if depth < 12 {
            for child in axChildren(el) {
                queue.append((child, depth + 1))
            }
        }
    }

    if let found = bestEl, bestScore >= 25.0 {
        return (found, bestScore, bestBrief)
    }
    if preferEditable && !hasSelector, let fallback = findInputElement(in: root, windowBounds: windowBounds) {
        return (fallback, 25.0, serializeAXElementBrief(fallback, windowBounds: windowBounds))
    }
    if preferEditable, let fallback = findInputElement(in: root, windowBounds: windowBounds), reqRole.isEmpty {
        return (fallback, 25.0, serializeAXElementBrief(fallback, windowBounds: windowBounds))
    }
    return nil
}

func cmdAppUseAxAction(flags: Set<String>, options: [String: String]) {
    guard AXIsProcessTrusted() else {
        writeJSON([
            "ok": false,
            "code": "ax_permission_denied",
            "error": "Accessibility permission is required.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    let (resolvedApp, windows, _) = resolveGenericAppAndWindows(options: options, allowLaunch: false, allowActivate: false)
    guard let app = resolvedApp else {
        writeJSON([
            "ok": false,
            "code": "app_not_running",
            "error": "Target app is not running.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    let targetWin = selectTargetWindow(in: windows, options: options)
    let effPID = targetWin?.pid ?? app.processIdentifier
    enableUniversalAccessibility(pid: effPID)
    let wb = targetWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) }

    guard let axWin = findGenericAXWindow(pid: effPID, targetWin: targetWin, reqTitle: options["window-title"]) else {
        writeJSON([
            "ok": false,
            "code": "ax_window_not_found",
            "error": "Target AX window not found without activation.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    guard let match = findBestMatchingAXElement(in: axWin, windowBounds: wb, options: options, preferEditable: false) else {
        writeJSON([
            "ok": false,
            "code": "ax_element_not_found",
            "error": "No matching AX control found.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }

    let reqAction = (options["ax-action"] ?? (kAXPressAction as String)).trimmingCharacters(in: .whitespacesAndNewlines)
    let actionName = reqAction.isEmpty ? (kAXPressAction as String) : reqAction

    var actionsCF: CFArray?
    let copyErr = AXUIElementCopyActionNames(match.element, &actionsCF)
    let supportedActions = (copyErr == .success ? (actionsCF as? [String]) : nil) ?? []
    if !supportedActions.isEmpty && !supportedActions.contains(actionName) {
        writeJSON([
            "ok": false,
            "code": "ax_action_unsupported",
            "error": "Matched control does not support \(actionName).",
            "supportedActions": supportedActions,
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
            "matchedElement": match.brief,
            "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
            "name": app.localizedName ?? (options["app-name"] ?? ""),
        ])
    }

    let performErr = AXUIElementPerformAction(match.element, actionName as CFString)
    var resp: [String: Any] = [
        "ok": performErr == .success,
        "channel": "headless_ax",
        "action": actionName,
        "axError": Int(performErr.rawValue),
        "stoleFocus": false,
        "touchedClipboard": false,
        "matchedElement": match.brief,
        "matchScore": match.score,
        "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
        "name": app.localizedName ?? (options["app-name"] ?? ""),
    ]
    if performErr != .success {
        resp["code"] = "ax_perform_failed"
        resp["error"] = "AXUIElementPerformAction(\(actionName)) failed with AXError \(performErr.rawValue)"
    }
    if let w = targetWin {
        resp["windowID"] = w.windowID
        resp["windowTitle"] = w.title
    }
    writeJSON(resp)
}

func cmdAppUseAxSetValue(flags: Set<String>, options: [String: String]) {
    guard AXIsProcessTrusted() else {
        writeJSON([
            "ok": false,
            "code": "ax_permission_denied",
            "error": "Accessibility permission is required.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    guard let text = options["text"] else {
        writeJSON([
            "ok": false,
            "code": "missing_argument",
            "error": "Missing --text argument.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    let (resolvedApp, windows, _) = resolveGenericAppAndWindows(options: options, allowLaunch: false, allowActivate: false)
    guard let app = resolvedApp else {
        writeJSON([
            "ok": false,
            "code": "app_not_running",
            "error": "Target app is not running.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    let targetWin = selectTargetWindow(in: windows, options: options)
    let effPID = targetWin?.pid ?? app.processIdentifier
    enableUniversalAccessibility(pid: effPID)
    let wb = targetWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) }

    guard let axWin = findGenericAXWindow(pid: effPID, targetWin: targetWin, reqTitle: options["window-title"]) else {
        writeJSON([
            "ok": false,
            "code": "ax_window_not_found",
            "error": "Target AX window not found without activation.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }
    guard let match = findBestMatchingAXElement(in: axWin, windowBounds: wb, options: options, preferEditable: true) else {
        writeJSON([
            "ok": false,
            "code": "ax_element_not_found",
            "error": "No editable AX element found.",
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
        ])
    }

    let wantSubmit = flags.contains("submit") || options["submit"] == "1"
    var actionsCF: CFArray?
    let copyErr = AXUIElementCopyActionNames(match.element, &actionsCF)
    let supportedActions = (copyErr == .success ? (actionsCF as? [String]) : nil) ?? []
    let supportsConfirm = supportedActions.contains(kAXConfirmAction as String)
    if wantSubmit && !supportsConfirm {
        writeJSON([
            "ok": false,
            "code": "submit_requires_hid",
            "error": "Matched editable control does not support AXConfirm for headless submit.",
            "supportedActions": supportedActions,
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
            "matchedElement": match.brief,
        ])
    }

    var isSettable: DarwinBoolean = false
    let settableErr = AXUIElementIsAttributeSettable(match.element, kAXValueAttribute as CFString, &isSettable)
    if settableErr != .success || !isSettable.boolValue {
        writeJSON([
            "ok": false,
            "code": "ax_value_not_settable",
            "error": "AXValue attribute is not settable on matched control.",
            "axError": Int(settableErr.rawValue),
            "channel": "headless_ax",
            "stoleFocus": false,
            "touchedClipboard": false,
            "matchedElement": match.brief,
        ])
    }

    let finalText: String
    if flags.contains("append") {
        let cur = axString(match.element, kAXValueAttribute) ?? ""
        finalText = cur + text
    } else {
        finalText = text
    }

    let writeErr = AXUIElementSetAttributeValue(match.element, kAXValueAttribute as CFString, finalText as CFTypeRef)
    usleep(80_000)
    let readback = axString(match.element, kAXValueAttribute) ?? ""
    let stripWS: (String) -> String = { s in
        String(s.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) })
    }
    let expectedStripped = stripWS(text)
    let verified = expectedStripped.isEmpty ? (writeErr == .success) : stripWS(readback).contains(expectedStripped)

    var submitted = false
    if wantSubmit && verified && supportsConfirm {
        submitted = (AXUIElementPerformAction(match.element, kAXConfirmAction as CFString) == .success)
    }

    let ok = (writeErr == .success && verified)
    var resp: [String: Any] = [
        "ok": ok,
        "verified": verified,
        "submitted": submitted,
        "channel": "headless_ax",
        "axError": Int(writeErr.rawValue),
        "stoleFocus": false,
        "touchedClipboard": false,
        "readbackSource": "ax_headless",
        "readbackPreview": readback.count > 260 ? String(readback.prefix(260)) : readback,
        "matchedElement": match.brief,
        "matchScore": match.score,
        "bundleID": app.bundleIdentifier ?? (options["bundle-id"] ?? ""),
        "name": app.localizedName ?? (options["app-name"] ?? ""),
    ]
    if !ok {
        resp["code"] = writeErr != .success ? "ax_set_value_failed" : "ax_readback_mismatch"
        resp["error"] = writeErr != .success ? "AXUIElementSetAttributeValue(kAXValue) failed with AXError \(writeErr.rawValue)" : "Headless AX readback did not match written text."
    }
    if let w = targetWin {
        resp["windowID"] = w.windowID
        resp["windowTitle"] = w.title
    }
    writeJSON(resp)
}

func cmdAppUseFocusSnapshot() {
    let front = NSWorkspace.shared.frontmostApplication
    let hid = queryHIDIdleState()
    let tsMs = Int64((Date().timeIntervalSince1970 * 1000.0).rounded())

    guard let app = front else {
        writeJSON([
            "ok": true,
            "tsMs": tsMs,
            "bundleID": "",
            "name": "",
            "pid": 0,
            "hid": hid,
        ])
    }

    let pid = app.processIdentifier
    let wins = listWindowsGeneric(for: [app])
    let mainWin = wins.first
    let winRect = mainWin.map { CGRect(x: $0.x, y: $0.y, width: $0.width, height: $0.height) }

    var cursorRelPoint: [String: Double]? = nil
    if let cur = hid["cursorPosition"] as? [String: Any],
       let cx = cur["x"] as? Double,
       let cy = cur["y"] as? Double,
       let wr = winRect,
       wr.width > 1, wr.height > 1,
       wr.contains(CGPoint(x: cx, y: cy)) {
        cursorRelPoint = [
            "x": ((cx - Double(wr.minX)) / Double(wr.width) * 1000.0).rounded() / 1000.0,
            "y": ((cy - Double(wr.minY)) / Double(wr.height) * 1000.0).rounded() / 1000.0,
        ]
    }

    var focusedDict: [String: Any]? = nil
    var cursorElDict: [String: Any]? = nil
    if AXIsProcessTrusted() {
        enableUniversalAccessibility(pid: pid)
        let axApp = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(axApp, 0.2)
        if let fRaw = axAttr(axApp, kAXFocusedUIElementAttribute) {
            let fEl = fRaw as! AXUIElement
            let serialized = serializeAXElementBrief(fEl, windowBounds: winRect)
            if !serialized.isEmpty { focusedDict = serialized }
        }
        if let cur = hid["cursorPosition"] as? [String: Any],
           let cx = cur["x"] as? Double,
           let cy = cur["y"] as? Double {
            var hitEl: AXUIElement?
            let err = AXUIElementCopyElementAtPosition(axApp, Float(cx), Float(cy), &hitEl)
            if err == .success, let el = hitEl {
                let serialized = serializeAXElementBrief(el, windowBounds: winRect)
                if !serialized.isEmpty { cursorElDict = serialized }
            }
        }
    }

    var resp: [String: Any] = [
        "ok": true,
        "tsMs": tsMs,
        "bundleID": app.bundleIdentifier ?? "",
        "name": app.localizedName ?? "",
        "pid": Int(pid),
        "appPath": app.bundleURL?.path ?? "",
        "windowCount": wins.count,
        "hid": hid,
    ]
    if let mw = mainWin { resp["window"] = mw.toDict() }
    if let crp = cursorRelPoint { resp["cursorRelPoint"] = crp }
    if let fd = focusedDict { resp["focusedElement"] = fd }
    if let ced = cursorElDict { resp["elementUnderCursor"] = ced }
    writeJSON(resp)
}

// MARK: - Main Dispatch

let parsed = parseArgs()
switch parsed.command {
case "status":
    cmdStatus(flags: parsed.flags, options: parsed.options)
case "list-mac-apps":
    cmdListMacApps(flags: parsed.flags, options: parsed.options)
case "app-use-activate":
    cmdAppUseActivate(flags: parsed.flags, options: parsed.options)
case "app-use-inspect":
    cmdAppUseInspect(flags: parsed.flags, options: parsed.options)
case "app-use-paste":
    cmdAppUsePaste(flags: parsed.flags, options: parsed.options)
case "app-use-ax-action":
    cmdAppUseAxAction(flags: parsed.flags, options: parsed.options)
case "app-use-ax-set-value":
    cmdAppUseAxSetValue(flags: parsed.flags, options: parsed.options)
case "app-use-focus-snapshot":
    cmdAppUseFocusSnapshot()
case "press-key":
    cmdPressKey(flags: parsed.flags, options: parsed.options)
case "list-app-windows":
    cmdListAppWindows(flags: parsed.flags, options: parsed.options)
case "dhash-windows":
    cmdDHashWindows(options: parsed.options)
case "hid-idle":
    writeJSON([
        "ok": true,
        "hidIdle": queryHIDIdleState(),
    ])
case "ax-tree":
    cmdAXTree(options: parsed.options)
case "ocr":
    cmdOCR(options: parsed.options)
case "capture-ocr":
    cmdCaptureOCR(options: parsed.options, allowActivation: !parsed.flags.contains("no-activate"))
case "set-window-frame":
    cmdSetWindowFrame(options: parsed.options)
case "extract-pdf-text":
    cmdExtractPDFText(options: parsed.options)
case "extract-video-frames":
    cmdExtractVideoFrames(options: parsed.options)
case "render-test-image":
    cmdRenderTestImage(options: parsed.options)
case "click":
    cmdClick(flags: parsed.flags, options: parsed.options)
case "right-click":
    cmdRightClick(flags: parsed.flags, options: parsed.options)
case "scroll":
    cmdScroll(options: parsed.options)
case "activate":
    cmdActivate(options: parsed.options)
case "request-permissions":
    cmdRequestPermissions(flags: parsed.flags)
case "focus-input":
    cmdFocusInput(options: parsed.options)
case "paste-and-verify":
    cmdPasteAndVerify(flags: parsed.flags, options: parsed.options)
case "send-sticker":
    cmdSendSticker(flags: parsed.flags, options: parsed.options)
case "paste-image":
    cmdPasteImage(flags: parsed.flags, options: parsed.options)
case "annotate-image":
    cmdAnnotateImage(options: parsed.options)
case "join-tencent-meeting":
    cmdJoinTencentMeeting(flags: parsed.flags, options: parsed.options)
case "setup-tencent-meeting":
    cmdSetupTencentMeeting(flags: parsed.flags, options: parsed.options)
case "audio-devices":
    cmdAudioDevices()
case "set-input-device":
    cmdSetInputDevice(flags: parsed.flags, options: parsed.options)
case "voice-call":
    cmdVoiceCall(flags: parsed.flags, options: parsed.options)
default:
    writeJSON([
        "ok": true,
        "usage": "wechat-vision-ax <status|list-mac-apps|app-use-activate|app-use-inspect|app-use-paste|app-use-ax-action|app-use-ax-set-value|app-use-focus-snapshot|press-key|list-app-windows|dhash-windows|hid-idle|ax-tree|ocr|capture-ocr|set-window-frame|extract-pdf-text|extract-video-frames|render-test-image|click|right-click|scroll|activate|request-permissions|focus-input|paste-and-verify|send-sticker|paste-image|annotate-image|join-tencent-meeting|setup-tencent-meeting|audio-devices|set-input-device|voice-call> [options]",
    ])
}
