import AppKit
import WebKit

private final class PreviewApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    let resources: URL
    let data: URL
    let smoke: URL?
    let reopen: Bool
    let guided: Bool
    let live: [String]
    private var window: NSWindow!
    private var web: WKWebView!
    private var service: Process?
    private var previewURL: URL?
    private var completed = false
    private var didNavigate = false

    init(resources: URL, data: URL, smoke: URL?, reopen: Bool, guided: Bool, live: [String]) {
        self.resources = resources; self.data = data; self.smoke = smoke; self.reopen = reopen
        self.guided = guided; self.live = live
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: settings)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 735),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = guided ? "微信工作台 · 辅助接待候选" : "微信工作台 · 推荐回复演练"
        window.contentMinSize = NSSize(width: 560, height: 600)
        window.contentView = web
        window.appearance = smoke != nil ? NSAppearance(named: .aqua) : nil
        window.center(); window.makeKeyAndOrderFront(nil)
        if smoke != nil { NSApp.activate(ignoringOtherApps: true) }
        start()
        DispatchQueue.main.asyncAfter(deadline: .now() + 32) { [weak self] in
            guard let self, !self.didNavigate || (self.smoke != nil && !self.completed) else { return }
            self.fail("预览服务或页面超时")
        }
    }

    private func start() {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        let mode = guided ? (live.isEmpty ? "guided-serve" : "guided-live") : "serve"
        process.arguments = ["-B", "-m", "wechat_control.recommendation_preview", mode, data.path]
        if !live.isEmpty {
            process.arguments?.append(resources.appendingPathComponent("wechat-vision-ax").path)
            process.arguments?.append(contentsOf: live)
        }
        process.currentDirectoryURL = resources
        process.environment = ["PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                               "PYTHONIOENCODING": "UTF-8", "LANG": "en_US.UTF-8"]
        process.standardOutput = pipe
        do { try process.run() } catch { fail("无法启动本地预览服务"); return }
        service = process
        DispatchQueue.global().async { [weak self] in
            let bytes = pipe.fileHandleForReading.availableData
            let payload = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any]
            DispatchQueue.main.async {
                guard let self, !self.completed else { return }
                guard let payload, payload["mode"] as? String == "isolated",
                      let port = payload["port"] as? Int, (1024...65535).contains(port),
                      let token = payload["token"] as? String,
                      token.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
                      let url = URL(string: "http://127.0.0.1:\(port)/workbench") else {
                    self.fail("无法验证预览服务身份"); return
                }
                self.previewURL = url
                var request = URLRequest(url: url)
                request.setValue(token, forHTTPHeaderField: "X-Workbench-Session")
                self.web.load(request)
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(action.request.url == previewURL && previewURL != nil ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        didNavigate = true
        guard let smoke else { return }
        if guided { exerciseGuided(smoke); return }
        let preamble = """
        const el = id => document.getElementById(id);
        async function wait(test) {
          for (let n=0;n<100;n++) { if (test()) return; await new Promise(r=>setTimeout(r,60)); }
          throw Error("UI state timeout");
        }
        function check(value,message) { if (!value) throw Error(message); }
        await wait(()=>document.querySelectorAll("#tasks li").length===2 && !el("detail").hidden);
        """
        if reopen {
            evaluate(preamble + """
            await wait(()=>el("state").textContent==="已采纳草稿");
            check(el("draft").textContent==="试用期是七天。","adopted text changed");
            check(document.querySelectorAll("#tasks li").length===2,"duplicate tasks on restart");
            check(el("timeline").textContent.includes("已采纳"),"missing event");
            check(el("review").hidden,"unexpected send control");
            return {persisted:true, count:2};
            """) { result in self.finish(result, file: "reopened.json") }
            return
        }
        evaluate(preamble + """
        check(document.querySelectorAll("#options input").length===3,"three real suggestions needed");
        check(document.querySelector("#options input:checked").value==="1","top one not selected");
        check(el("refs").textContent.includes("试用期限"),"no knowledge citation");
        check(el("review").hidden,"unexpected send control");
        return {twoTasks:true, threeOptions:true, topOneDefault:true, knowledge:true};
        """) { initial in
            self.snapshot(smoke.appendingPathComponent("native-light.png")) {
                self.window.appearance = NSAppearance(named: .darkAqua)
                self.window.setContentSize(NSSize(width: 560, height: 630))
                self.evaluate(preamble + """
                await wait(()=>matchMedia("(prefers-color-scheme: dark)").matches && innerWidth===560);
                check(document.documentElement.scrollWidth<=innerWidth,"horizontal overflow");
                el("choices").scrollIntoView({block:"start"});
                return {dark:true, width:innerWidth};
                """) { narrow in
                    self.snapshot(smoke.appendingPathComponent("native-dark.png")) {
                        self.exercise(preamble: preamble, initial: initial, narrow: narrow)
                    }
                }
            }
        }
    }

    private func exercise(preamble: String, initial: [String: Any], narrow: [String: Any]) {
        evaluate(preamble + """
        const token = document.querySelector('meta[name="workbench-session"]').content;
        const headers = {"X-Workbench-Session":token,"Content-Type":"application/json"};
        const tasks = (await (await fetch("/api/workbench/tasks",{headers})).json()).tasks;
        check(tasks.length===2 && tasks[0].state==="ready","not backed by actual pending list");
        const choice = document.querySelector('#options input[value="2"]');
        choice.click();
        check(choice.checked,"cannot select second suggestion");
        el("adopt").click();
        await wait(()=>el("state").textContent==="已采纳草稿" && !el("adopt").disabled);
        check(el("draft").textContent==="试用期是七天。","selected draft was not saved");
        const reopened = (await (await fetch("/api/workbench/tasks/"+tasks[0].id,{headers})).json()).task;
        const rejected = await fetch("/api/workbench/adopt",{method:"POST",headers,
          body:JSON.stringify({id:tasks[0].id,version:tasks[0].version,choice:"1"})});
        check(rejected.status===409,"stale choice was accepted");
        const send = await fetch("/api/workbench/confirm",{method:"POST",headers,body:"{}"});
        const legacy = await fetch("/send",{method:"POST",headers,body:"{}"});
        const unauth = await fetch("/api/workbench/tasks");
        check(send.status===403 && legacy.status===404 && unauth.status===403,"isolation fence failed");
        document.querySelectorAll("#tasks button")[1].click();
        await wait(()=>el("state").textContent==="待人工处理");
        check(el("refs").childElementCount===0 && el("adopt").hidden,"invented recommendation");
        el("defer").click();
        await wait(()=>el("state").textContent==="已暂缓");
        return {adopted:reopened.basis.adopted, stale:rejected.status, confirm:send.status,
                legacySend:legacy.status, unauthorized:unauth.status, noKnowledge:true, deferred:true};
        """) { outcome in
            self.finish(["initial":initial,"narrow":narrow,"outcome":outcome], file:"native-smoke.json")
        }
    }

    private func exerciseGuided(_ output: URL) {
        let helper = """
        const el=id=>document.getElementById(id), rows=()=>document.querySelectorAll("#tasks li").length;
        async function wait(f) {for(let i=0;i<35;i++){if(f())return;await refresh();if(f())return;await new Promise(r=>setTimeout(r,100));}throw Error("wait failed: "+el("monitor-status").textContent+" / "+el("state").textContent);}
        function check(x,m){if(!x)throw Error(m);}
        const word=s=>el("monitor-status").textContent.includes(s);
        const token=document.querySelector('meta[name="workbench-session"]').content;
        const headers={"Content-Type":"application/json","X-Workbench-Session":token};
        const post=(p,b)=>fetch("/api/workbench/"+p,{method:"POST",headers,body:JSON.stringify(b)});
        """
        if reopen {
            evaluate(helper + """
            await wait(()=>el("state").textContent==="本机已核验");
            check(rows()===1&&el("timeline").textContent.includes("同一会话读回"),"missing reopened receipt");
            check(el("toggle-monitor").disabled,"monitor must be re-confirmed after restart");
            return {reopened:true, monitorStopped:true};
            """) { self.finish($0,file:"guided-reopened.json") }
            return
        }
        evaluate(helper + """
        await wait(()=>el("window-picker").options.length===1);
        check(rows()===0 && el("toggle-monitor").disabled,"capture started before confirmation");
        check((await post("capture",{})).status===409,"unconfirmed capture accepted");
        el("bind-window").click();
        await wait(()=>word("尚未开始")&&!busy);
        check(rows()===0,"window confirm started capture");
        el("toggle-monitor").click();
        await wait(()=>word("正在监看")&&!busy);
        await post("capture",{});
        await wait(()=>rows()===1&&document.querySelectorAll("#options input").length===3);
        el("toggle-monitor").click();
        await wait(()=>word("已暂停")&&!busy);
        check((await post("capture",{})).status===409,"paused capture accepted");
        document.querySelector('#options input[value="2"]').click();
        el("adopt").click();
        await wait(()=>el("state").textContent==="已采纳草稿"&&!el("review").disabled);
        el("review").click();
        check(el("confirm").open&&el("to").textContent.includes("演练好友")&&el("content").textContent==="试用期是七天。","wrong confirmation");
        check(document.activeElement.textContent==="取消","unsafe initial focus");
        return {selected:true,started:true,paused:true,oneTask:true,adopted:true};
        """) { first in
            self.snapshot(output.appendingPathComponent("guided-confirm.png")) {
                self.evaluate(helper + """
                el("confirm").querySelector('[value="cancel"]').click();
                await wait(()=>!el("confirm").open);
                check(el("state").textContent==="已采纳草稿","cancel submitted the send");
                el("review").click();
                el("confirm-send").click();
                await wait(()=>el("state").textContent==="本机已核验");
                const tasks=(await (await fetch("/api/workbench/tasks",{headers})).json()).tasks;
                const task=tasks[0];
                const repeated=await post("confirm",{id:task.id,version:task.version,text:task.draft});
                const again=(await repeated.json()).task;
                check(again.state==="verified"&&again.events.filter(e=>e.stage==="sending").length===1,"duplicate send");
                check((await fetch("/send",{method:"POST",headers,body:"{}"})).status===404,"legacy route accessible");
                return {cancelled:true,receipt:true,oneSend:true,legacyBlocked:true};
                """) { last in
                    self.snapshot(output.appendingPathComponent("guided-receipt.png")) {
                        self.finish(["beforeSend":first,"afterSend":last],file:"guided-smoke.json")
                    }
                }
            }
        }
    }

    private func evaluate(_ code: String, next: @escaping ([String: Any]) -> Void) {
        Task { @MainActor in
            do {
                let value = try await web.callAsyncJavaScript(code, arguments: [:], in: nil, contentWorld: .page)
                guard let dictionary = value as? [String: Any] else { self.fail("页面返回无效"); return }
                next(dictionary)
            } catch {
                self.fail(String(describing: error))
            }
        }
    }

    private func snapshot(_ output: URL, next: @escaping () -> Void) {
        web.takeSnapshot(with: nil) { image, error in
            guard error == nil, let bytes = image?.tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: bytes),
                  let png = bitmap.representation(using: .png, properties: [:]) else {
                self.fail("无法保存实机截图"); return
            }
            do { try png.write(to: output, options: .atomic); next() }
            catch { self.fail("无法写入实机截图") }
        }
    }

    private func finish(_ data: [String: Any], file: String) {
        guard let smoke else { return }
        do {
            let bytes = try JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys])
            try bytes.write(to: smoke.appendingPathComponent(file), options: .atomic)
            completed = true
            NSApp.terminate(nil)
        } catch { fail("无法写入验收结果") }
    }

    private func fail(_ reason: String) {
        completed = true
        fputs(reason + "\n", stderr)
        if smoke != nil {
            if service?.isRunning == true { service?.terminate() }
            exit(1)
        }
        let label = NSTextField(wrappingLabelWithString: reason)
        label.alignment = .center
        window.contentView = label
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        if service?.isRunning == true { service?.terminate() }
    }
}

private let args = Array(CommandLine.arguments.dropFirst())
private let guided = Bundle.main.bundleIdentifier == "com.openbot.wechat-bot.guided-preview"
guard let resources = Bundle.main.resourceURL else { exit(2) }
if args == ["--verify-headless"] {
    let source = resources.appendingPathComponent("wechat_control/recommendation_preview.py")
    let page = resources.appendingPathComponent("wechat_control/workbench.html")
    let driver = resources.appendingPathComponent("wechat-vision-ax")
    let ok = FileManager.default.isReadableFile(atPath: source.path) && FileManager.default.isReadableFile(atPath: page.path)
        && (!guided || FileManager.default.isExecutableFile(atPath: driver.path))
    print("{\"isolated\":true,\"guided\":\(guided),\"packageValid\":\(ok)}"); exit(ok ? 0 : 2)
}
private let smoke = args.count == 2 && ["--smoke", "--smoke-reopen"].contains(args[0])
    ? URL(fileURLWithPath: args[1], isDirectory: true).resolvingSymlinksInPath() : nil
private let live = guided && args.count == 3 && args[0] == "--live-test" && !args[1].isEmpty && !args[2].isEmpty
    ? Array(args.dropFirst()) : []
if !args.isEmpty && live.isEmpty && (smoke == nil || !smoke!.path.hasPrefix("/Volumes/SanDisk/Builds/wechat-studio/")) { exit(2) }
private let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
private let folder = guided ? "WeChat Workbench Guided Preview" : "WeChat Workbench Recommendation Preview"
private let defaultData = support.appendingPathComponent(folder)
private let data = smoke?.appendingPathComponent("ui-data") ?? (guided
    ? defaultData.appendingPathComponent(live.isEmpty ? "rehearsal" : "manual-test-"+UUID().uuidString)
    : defaultData)
private let app = NSApplication.shared
app.setActivationPolicy(.regular)
private let delegate = PreviewApp(resources: resources,data: data,smoke: smoke,reopen: args.first == "--smoke-reopen",
                                  guided: guided, live: live)
app.delegate = delegate
app.run()
