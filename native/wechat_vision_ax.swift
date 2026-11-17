import AppKit
import ApplicationServices
import AVFoundation
import CoreGraphics
import Foundation
import ImageIO
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

// MARK: - Accessibility Helpers

let wechatBundleID = "com.tencent.xinWeChat"
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

func findWeChatApp() -> NSRunningApplication? {
    if let byBundle = NSRunningApplication.runningApplications(withBundleIdentifier: wechatBundleID).first {
        return byBundle
    }
    for app in NSWorkspace.shared.runningApplications {
        let name = app.localizedName ?? ""
        if name == "WeChat" || name == "微信" {
            return app
        }
    }
    return nil
}

func isWeChatFrontmost() -> (Bool, String) {
    guard let front = NSWorkspace.shared.frontmostApplication else {
        return (false, "none")
    }
    let bid = front.bundleIdentifier ?? ""
    let name = front.localizedName ?? ""
    let match = (bid == wechatBundleID) || (name == "WeChat") || (name == "微信")
    return (match, "\(name) (\(bid))")
}

struct WindowCandidate {
    let windowID: CGWindowID
    let title: String
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    var area: Double { width * height }
}

func listWeChatWindows(pid: pid_t) -> [WindowCandidate] {
    guard let rawList = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return []
    }
    var result: [WindowCandidate] = []
    for entry in rawList {
        guard let ownerPID = entry[kCGWindowOwnerPID as String] as? pid_t,
              ownerPID == pid,
              (entry[kCGWindowLayer as String] as? Int) == 0,
              let num = entry[kCGWindowNumber as String] as? NSNumber,
              let bounds = entry[kCGWindowBounds as String] as? [String: Any],
              let w = (bounds["Width"] as? NSNumber)?.doubleValue,
              let h = (bounds["Height"] as? NSNumber)?.doubleValue,
              w >= 200, h >= 180 else {
            continue
        }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let title = (entry[kCGWindowName as String] as? String) ?? ""
        result.append(WindowCandidate(windowID: num.uint32Value, title: title, x: x, y: y, width: w, height: h))
    }
    result.sort { lhs, rhs in
        let lPref = (lhs.title == "微信" || lhs.title == "WeChat") ? 1 : 0
        let rPref = (rhs.title == "微信" || rhs.title == "WeChat") ? 1 : 0
        if lPref != rPref { return lPref > rPref }
        return lhs.area > rhs.area
    }
    return result
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

func findMainAXWindow(pid: pid_t) -> AXUIElement? {
    guard AXIsProcessTrusted() else { return nil }
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
        if title == "微信" || title == "WeChat" { score += 10_000_000 }
        if axHasSessionList(win) { score += 50_000_000 }
        if score > bestScore {
            bestScore = score
            bestWindow = win
        }
    }
    return bestWindow ?? windows.first
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

func queryHIDIdleState() -> [String: Any] {
    let mouseMove = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .mouseMoved)
    let leftDown = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .leftMouseDown)
    let rightDown = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .rightMouseDown)
    let scrollWheel = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .scrollWheel)
    let keyDown = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown)
    let flagsChanged = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .flagsChanged)

    let mouseIdle = min(mouseMove, leftDown, rightDown, scrollWheel)
    let keyboardIdle = min(keyDown, flagsChanged)
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

func captureWindowImage(_ window: WindowCandidate) -> CGImage? {
    return CGWindowListCreateImage(
        .null,
        .optionIncludingWindow,
        window.windowID,
        [.boundsIgnoreFraming, .bestResolution]
    )
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

func postKey(keyCode: CGKeyCode, flags: CGEventFlags = []) {
    let src = CGEventSource(stateID: .hidSystemState)
    if let down = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: true),
       let up = CGEvent(keyboardEventSource: src, virtualKey: keyCode, keyDown: false) {
        down.flags = flags
        up.flags = flags
        down.post(tap: .cghidEventTap)
        usleep(20_000)
        up.post(tap: .cghidEventTap)
    }
}

// Keycodes (macOS Carbon HIToolbox US QWERTY virtual keys)
let kKeyA: CGKeyCode = 0
let kKeyC: CGKeyCode = 8
let kKeyV: CGKeyCode = 9
let kKeyReturn: CGKeyCode = 36
let kKeyDelete: CGKeyCode = 51
let kKeyRightArrow: CGKeyCode = 124

func findInputElement(in root: AXUIElement, maxNodes: Int = 900) -> AXUIElement? {
    var queue = [root]
    var idx = 0
    var fallbackTextArea: AXUIElement?
    while idx < queue.count && idx < maxNodes {
        let el = queue[idx]
        idx += 1
        let ident = axString(el, kAXIdentifierAttribute) ?? ""
        let role = axString(el, kAXRoleAttribute) ?? ""
        if inputIdentifiers.contains(ident) {
            return el
        }
        if role == kAXTextAreaRole as String && fallbackTextArea == nil {
            fallbackTextArea = el
        }
        queue.append(contentsOf: axChildren(el))
    }
    return fallbackTextArea
}

func runOpenWeChatProcess() {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    proc.arguments = ["-b", wechatBundleID]
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

func axUnminimizeAndRaiseWeChatWindows(pid: pid_t) -> Bool {
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
        if title == "微信" || title == "WeChat" || (sz.width >= 320 && sz.height >= 240) {
            _ = AXUIElementPerformAction(win, kAXRaiseAction as CFString)
            acted = true
        }
    }
    return acted
}

func pressWeChatWindowMenu(pid: pid_t) -> Bool {
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
                if title == "微信" || title == "WeChat" || title == "聊天" || title == "前置全部窗口" {
                    if AXUIElementPerformAction(item, kAXPressAction as CFString) == .success {
                        return true
                    }
                }
            }
        }
    }
    return false
}

func findWeChatDockItem() -> AXUIElement? {
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
           (title == "微信" || title == "WeChat") {
            return el
        }
        queue.append(contentsOf: axChildren(el))
    }
    return nil
}

func clickWeChatInDock() -> String? {
    guard let dockItem = findWeChatDockItem() else { return nil }
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

/// Ensures WeChat is running, unminimized, visible as an on-screen window, and frontmost.
func ensureWeChatMainWindow() -> (app: NSRunningApplication?, windows: [WindowCandidate], recoveryMethod: String?) {
    var recoveryMethod: String? = nil
    var app = findWeChatApp()

    // Stage 1: Launch WeChat via bundle ID if not running
    if app == nil {
        runOpenWeChatProcess()
        for _ in 0..<12 {
            usleep(250_000)
            app = findWeChatApp()
            if app != nil { break }
        }
        if app != nil { recoveryMethod = "open_launch" }
    }
    guard let runningApp = app else {
        return (nil, [], nil)
    }

    var windows = listWeChatWindows(pid: runningApp.processIdentifier)
    if windows.isEmpty {
        // Stage 2: Unhide + Activate + AX Unminimize & Raise
        _ = runningApp.unhide()
        _ = runningApp.activate(options: [.activateIgnoringOtherApps])
        if axUnminimizeAndRaiseWeChatWindows(pid: runningApp.processIdentifier) {
            usleep(350_000)
            windows = listWeChatWindows(pid: runningApp.processIdentifier)
            if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? "ax_unminimize"
            }
        }
    }

    if windows.isEmpty {
        // Stage 3a: `/usr/bin/open -b com.tencent.xinWeChat` (triggers macOS Reopen Application AppleEvent)
        runOpenWeChatProcess()
        usleep(400_000)
        windows = listWeChatWindows(pid: runningApp.processIdentifier)
        if !windows.isEmpty {
            recoveryMethod = recoveryMethod ?? "open_reopen"
        }
    }

    if windows.isEmpty {
        // Stage 3b: Trigger WeChat menu bar "窗口" -> "微信"/"聊天"
        _ = runningApp.activate(options: [.activateIgnoringOtherApps])
        usleep(180_000)
        if pressWeChatWindowMenu(pid: runningApp.processIdentifier) {
            usleep(350_000)
            windows = listWeChatWindows(pid: runningApp.processIdentifier)
            if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? "menu_bar_window"
            }
        }
    }

    if windows.isEmpty {
        // Stage 4: Find & click "微信" Dock icon (AXPress first, then physical CGEvent click)
        if let dockMethod = clickWeChatInDock() {
            usleep(450_000)
            windows = listWeChatWindows(pid: runningApp.processIdentifier)
            if windows.isEmpty, let dockItem = findWeChatDockItem(), CGPreflightPostEventAccess(),
               let pt = axPoint(dockItem, kAXPositionAttribute),
               let sz = axSize(dockItem, kAXSizeAttribute),
               sz.width > 0 && sz.height > 0 {
                moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
                usleep(450_000)
                windows = listWeChatWindows(pid: runningApp.processIdentifier)
                if !windows.isEmpty { recoveryMethod = "dock_cgevent_click" }
            } else if !windows.isEmpty {
                recoveryMethod = recoveryMethod ?? dockMethod
            }
        }
    }

    _ = runningApp.activate(options: [.activateIgnoringOtherApps])
    usleep(220_000)
    if windows.isEmpty {
        windows = listWeChatWindows(pid: runningApp.processIdentifier)
    }
    return (runningApp, windows, recoveryMethod)
}

// MARK: - Subcommands

func cmdStatus(flags: Set<String> = []) {
    let axTrusted = AXIsProcessTrusted()
    let scTrusted = CGPreflightScreenCaptureAccess()
    let postTrusted = CGPreflightPostEventAccess()
    let (frontOK, frontDesc) = isWeChatFrontmost()
    let app = findWeChatApp()

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
        "accessibilityTrusted": axTrusted,
        "postEventTrusted": postTrusted,
        "screenCaptureTrusted": scTrusted,
        "wechatRunning": app != nil,
        "wechatFrontmost": frontOK,
        "frontmostApp": frontDesc,
        "hidIdle": queryHIDIdleState(),
        "screens": screenList,
    ]

    if let app = app {
        payload["wechatPID"] = app.processIdentifier
        payload["wechatBundleID"] = app.bundleIdentifier ?? ""
        let windows = listWeChatWindows(pid: app.processIdentifier)
        payload["windowCount"] = windows.count
        payload["windows"] = windows.map { win in
            [
                "windowID": win.windowID,
                "title": win.title,
                "bounds": ["x": win.x, "y": win.y, "width": win.width, "height": win.height],
            ] as [String: Any]
        }

        if flags.contains("with-chat-title") {
            let axTitle = readChatTitleFromAX(pid: app.processIdentifier)
            if let name = axTitle.name {
                payload["currentChatTitle"] = name
                payload["currentChatSource"] = "accessibility"
                if let count = axTitle.memberCount {
                    payload["currentChatMemberCount"] = count
                }
            } else if let mainWin = windows.first, let ocrTitle = parseTitleFromHeaderOCR(mainWin) {
                payload["currentChatTitle"] = ocrTitle
                payload["currentChatSource"] = "vision_ocr"
            }
        }
    }

    writeJSON(payload)
}

func cmdAXTree(options: [String: String]) {
    guard AXIsProcessTrusted() else {
        failJSON("Accessibility permission (AXIsProcessTrusted) is not granted.", code: "ax_permission_denied")
    }
    guard let app = findWeChatApp() else {
        failJSON("WeChat (com.tencent.xinWeChat) is not running.", code: "wechat_not_running")
    }
    guard let win = findMainAXWindow(pid: app.processIdentifier) else {
        failJSON("No accessible WeChat main window found.", code: "no_ax_window")
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
        "wechatPID": app.processIdentifier,
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
    let reqWindowID = options["window-id"].flatMap { UInt32($0) }
    let reqWindowTitle = options["window-title"]?.trimmingCharacters(in: .whitespacesAndNewlines)

    var app = findWeChatApp()
    var windows: [WindowCandidate] = app.map { listWeChatWindows(pid: $0.processIdentifier) } ?? []
    if allowActivation && (app == nil || (reqWindowID == nil && (reqWindowTitle == nil || reqWindowTitle!.isEmpty) && windows.isEmpty)) {
        let ensured = ensureWeChatMainWindow()
        app = ensured.app
        if !ensured.windows.isEmpty {
            windows = ensured.windows
        } else if let a = app {
            windows = listWeChatWindows(pid: a.processIdentifier)
        }
    }
    guard let runningApp = app else {
        failJSON("WeChat is not running and could not be launched.", code: "wechat_not_running")
    }
    if windows.isEmpty {
        windows = listWeChatWindows(pid: runningApp.processIdentifier)
    }

    let targetWin: WindowCandidate?
    if let wid = reqWindowID {
        targetWin = windows.first { $0.windowID == wid }
    } else if let titleSub = reqWindowTitle, !titleSub.isEmpty {
        let lowSub = titleSub.lowercased()
        targetWin = windows.first { $0.title.lowercased() == lowSub }
            ?? windows.first { $0.title.lowercased().contains(lowSub) }
    } else {
        targetWin = windows.first
    }

    guard let mainWin = targetWin else {
        failJSON(
            "No matching visible WeChat window found.",
            code: (reqWindowID != nil || reqWindowTitle != nil) ? "window_not_found" : "no_window",
            extra: [
                "availableWindows": windows.map { ["windowID": $0.windowID, "title": $0.title] as [String: Any] }
            ]
        )
    }
    guard let cgImage = captureWindowImage(mainWin) else {
        failJSON("CGWindowListCreateImage returned nil.", code: "capture_failed")
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
    guard let app = findWeChatApp() else {
        failJSON("WeChat (com.tencent.xinWeChat) is not running.", code: "wechat_not_running")
    }
    let axApp = AXUIElementCreateApplication(app.processIdentifier)
    AXUIElementSetMessagingTimeout(axApp, 0.5)

    var targetWin: AXUIElement? = nil
    let reqTitle = options["window-title"]?.trimmingCharacters(in: .whitespacesAndNewlines)
    if let titleSub = reqTitle, !titleSub.isEmpty,
       let windows = axAttr(axApp, kAXWindowsAttribute) as? [AXUIElement] {
        let low = titleSub.lowercased()
        targetWin = windows.first { (axString($0, kAXTitleAttribute) ?? "").lowercased() == low }
            ?? windows.first { (axString($0, kAXTitleAttribute) ?? "").lowercased().contains(low) }
    }
    if targetWin == nil {
        targetWin = findMainAXWindow(pid: app.processIdentifier)
    }
    guard let win = targetWin else {
        failJSON("No matching accessible WeChat window found.", code: "no_ax_window")
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
        let ensured = ensureWeChatMainWindow()
        guard let win = ensured.windows.first else {
            failJSON("No visible WeChat main window for relative scroll.", code: "no_visible_wechat_window")
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

func cmdActivate() {
    let ensured = ensureWeChatMainWindow()
    guard let app = ensured.app else {
        failJSON("WeChat is not running and could not be launched.", code: "wechat_not_running")
    }
    let activated = app.activate(options: [.activateIgnoringOtherApps])
    usleep(200_000)
    let (frontOK, frontDesc) = isWeChatFrontmost()
    let windows = ensured.windows.isEmpty ? listWeChatWindows(pid: app.processIdentifier) : ensured.windows
    var resp: [String: Any] = [
        "ok": frontOK && !windows.isEmpty,
        "activatedCall": activated,
        "wechatFrontmost": frontOK,
        "frontmostApp": frontDesc,
        "wechatPID": app.processIdentifier,
        "windowCount": windows.count,
        "windows": windows.map { win in
            [
                "windowID": win.windowID,
                "title": win.title,
                "bounds": ["x": win.x, "y": win.y, "width": win.width, "height": win.height],
            ] as [String: Any]
        },
    ]
    if let method = ensured.recoveryMethod {
        resp["recoveryMethod"] = method
    }
    writeJSON(resp, exitCode: (frontOK && !windows.isEmpty) ? 0 : 1)
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

func cmdFocusInput() {
    let ensured = ensureWeChatMainWindow()
    guard let app = ensured.app else {
        failJSON("WeChat is not running.", code: "wechat_not_running")
    }
    if let axWin = findMainAXWindow(pid: app.processIdentifier),
       let inputEl = findInputElement(in: axWin) {
        let focusErr = AXUIElementSetAttributeValue(inputEl, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let pt = axPoint(inputEl, kAXPositionAttribute)
        let sz = axSize(inputEl, kAXSizeAttribute)
        if let pt = pt, let sz = sz {
            let cx = pt.x + sz.width / 2.0
            let cy = pt.y + sz.height / 2.0
            moveAndClick(x: cx, y: cy)
            writeJSON([
                "ok": true,
                "method": "ax_and_click",
                "axFocusErr": focusErr.rawValue,
                "clickPoint": ["x": cx, "y": cy],
            ])
        } else if focusErr == .success {
            writeJSON(["ok": true, "method": "ax_focus_only"])
        }
    }

    // Fallback to window bottom-center heuristic (dead-center in WeChat 4.x input box above bottom toolbar)
    let windows = listWeChatWindows(pid: app.processIdentifier)
    guard let win = windows.first else {
        failJSON("No WeChat window found to focus input.", code: "no_window")
    }
    let cx = win.x + win.width * 0.60
    let cy = win.y + win.height - 85.0
    moveAndClick(x: cx, y: cy)
    writeJSON([
        "ok": true,
        "method": "window_geometry_fallback",
        "clickPoint": ["x": cx, "y": cy],
    ])
}

// Human-reviewed send: never navigate, use cursor geometry, or append to a user draft.
func cmdReviewedSend(text: String, expectedID: UInt32, expectedTitle: String) {
    guard AXIsProcessTrusted(), CGPreflightPostEventAccess() else {
        failJSON("WeChat input permissions required.", code: "review_ax_denied")
    }
    guard let app = findWeChatApp() else {
        failJSON("WeChat window changed.", code: "review_target_changed")
    }
    let pid = app.processIdentifier
    func sameChat() -> Bool {
        let windows = listWeChatWindows(pid: pid)
        guard windows.count == 1, let win = windows.first, win.windowID == expectedID else { return false }
        if let title = readChatTitleFromAX(pid: pid).name { return title == expectedTitle }
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
    guard sameChat() else { failJSON("WeChat conversation changed.", code: "review_target_changed") }
    _ = app.activate(options: [.activateIgnoringOtherApps])
    usleep(200_000)
    guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid, sameChat(),
          let axWindow = findMainAXWindow(pid: pid), let input = findInputElement(in: axWindow),
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
    let wantSend = flags.contains("send")
    let silentMode = flags.contains("silent") || !wantSend
    if options["review-window"] != nil || options["review-title"] != nil ||
       flags.contains("review-window") || flags.contains("review-title") {
        guard !silentMode, let id = options["review-window"].flatMap(UInt32.init),
              let title = options["review-title"], !title.isEmpty else {
            failJSON("Invalid reviewed send target.", code: "review_target_changed")
        }
        cmdReviewedSend(text: text, expectedID: id, expectedTitle: title)
        return
    }

    let ensured = ensureWeChatMainWindow()
    guard let app = ensured.app else {
        failJSON("WeChat is not running.", code: "wechat_not_running")
    }
    _ = app.activate(options: [.activateIgnoringOtherApps])
    usleep(200_000)

    let (frontOK, frontDesc) = isWeChatFrontmost()
    guard frontOK else {
        failJSON("Aborted: frontmost app is '\(frontDesc)', expected WeChat.", code: "not_frontmost")
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

    // Focus input element via AX or geometry
    let mainWin = listWeChatWindows(pid: app.processIdentifier).first
    var axInputEl: AXUIElement? = nil
    if let axWin = findMainAXWindow(pid: app.processIdentifier) {
        axInputEl = findInputElement(in: axWin)
        if let el = axInputEl {
            _ = AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            if let pt = axPoint(el, kAXPositionAttribute), let sz = axSize(el, kAXSizeAttribute) {
                moveAndClick(x: pt.x + sz.width / 2.0, y: pt.y + sz.height / 2.0)
            }
        }
    }
    if axInputEl == nil, let win = mainWin {
        moveAndClick(x: win.x + win.width * 0.60, y: win.y + win.height - 85.0)
    }
    usleep(180_000)

    // Paste text
    pb.clearContents()
    pb.setString(text, forType: .string)
    postKey(keyCode: kKeyV, flags: .maskCommand)
    usleep(250_000)

    // Readback verification (AXValue first, then Cmd+A + Cmd+C, then Vision OCR fallback)
    var readback = ""
    var readbackSource = "ax"
    if let el = axInputEl, let axVal = axString(el, kAXValueAttribute) {
        readback = axVal
    } else {
        readbackSource = "clipboard"
        pb.clearContents()
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(80_000)
        postKey(keyCode: kKeyC, flags: .maskCommand)
        usleep(160_000)
        readback = pb.string(forType: .string) ?? ""
    }

    if readback.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
       CGPreflightScreenCaptureAccess(),
       let win = mainWin,
       let image = captureWindowImage(win) {
        let imgW = Double(image.width)
        let imgH = Double(image.height)
        let scale = imgW / max(win.width, 1.0)
        let cropX = min(max(0.0, imgW * 0.36), max(0.0, imgW - 10.0))
        let cropY = max(0.0, imgH - 155.0 * scale)
        let cropW = min(imgW * 0.62, imgW - cropX)
        let cropH = min(115.0 * scale, imgH - cropY)
        if cropW > 10.0 && cropH > 10.0,
           let cropped = image.cropping(to: CGRect(x: cropX, y: cropY, width: cropW, height: cropH)),
           let results = try? runVisionOCR(cgImage: cropped) {
            let joined = results.compactMap { $0["text"] as? String }.joined(separator: " ")
            if !joined.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                readback = joined
                readbackSource = "vision_ocr"
            }
        }
    }

    // 3x length dirty-input circuit breaker (adapted from wechat-mac-rpa)
    if readback.count > text.count * 3 {
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete)
        restoreClipboard()
        failJSON(
            "Dirty input circuit breaker triggered: readback length \(readback.count) > 3x expected \(text.count).",
            code: "dirty_input_circuit_breaker",
            extra: ["expectedLen": text.count, "readbackLen": readback.count]
        )
    }

    let trimmedExpected = text.trimmingCharacters(in: .whitespacesAndNewlines)
    let ocrCompactMatch: Bool = {
        guard readbackSource == "vision_ocr" else { return false }
        let stripWS: (String) -> String = { s in
            String(s.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) })
        }
        return stripWS(readback).contains(stripWS(trimmedExpected))
    }()
    guard readback.contains(trimmedExpected) || ocrCompactMatch else {
        restoreClipboard()
        failJSON(
            "Readback verification mismatch.",
            code: "readback_mismatch",
            extra: ["expected": text, "readback": readback, "readbackSource": readbackSource]
        )
    }

    var sent = false
    if silentMode {
        // Clear input so nothing stays staged in silent verification mode
        postKey(keyCode: kKeyA, flags: .maskCommand)
        usleep(60_000)
        postKey(keyCode: kKeyDelete)
    } else {
        postKey(keyCode: kKeyRightArrow)
        usleep(60_000)
        postKey(keyCode: kKeyReturn)
        usleep(250_000)
        sent = true
    }

    restoreClipboard()
    writeJSON([
        "ok": true,
        "verified": true,
        "sent": sent,
        "silentMode": silentMode,
        "readbackLength": readback.count,
        "readbackSource": readbackSource,
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

// MARK: - Main Dispatch

let parsed = parseArgs()
switch parsed.command {
case "status":
    cmdStatus(flags: parsed.flags)
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
    cmdActivate()
case "request-permissions":
    cmdRequestPermissions(flags: parsed.flags)
case "focus-input":
    cmdFocusInput()
case "paste-and-verify":
    cmdPasteAndVerify(flags: parsed.flags, options: parsed.options)
default:
    writeJSON([
        "ok": true,
        "usage": "wechat-vision-ax <status|hid-idle|ax-tree|ocr|capture-ocr|set-window-frame|extract-video-frames|render-test-image|click|scroll|activate|request-permissions|focus-input|paste-and-verify> [options]",
    ])
}
