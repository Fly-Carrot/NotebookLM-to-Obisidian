import SwiftUI
import AppKit

final class SyncController: ObservableObject {
    @Published var status: String = "Ready"
    @Published var isRunning: Bool = false
    @Published var progressCurrent: Double = 0
    @Published var progressTotal: Double = 1
    @Published var exportPath: String
    @Published var isLoggedIn: Bool = false

    private let projectRoot: String
    private let fullSyncScriptPath: String
    private let pythonPath: String
    private let userDefaultsKey = "n2o_export_path"

    private var process: Process?
    private var loginPollTimer: DispatchSourceTimer?
    private var outputCarry: String = ""
    private var userStoppedSync: Bool = false

    init() {
        let defaultProjectRoot = "/Users/david_chen/Desktop/MCP_Hub/Obsidian Transfer"
        let bundleURL = Bundle.main.bundleURL
        let launchersDir = bundleURL.deletingLastPathComponent().path
        let inferredRoot = URL(fileURLWithPath: launchersDir).deletingLastPathComponent().path
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: "\(inferredRoot)/scripts/run_full_sync.sh") {
            projectRoot = inferredRoot
        } else {
            projectRoot = defaultProjectRoot
        }

        fullSyncScriptPath = "\(projectRoot)/scripts/run_full_sync.sh"
        pythonPath = "\(projectRoot)/Obsidian_Transfer_venv/bin/python"

        let defaultPath = "/Users/david_chen/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Memory"
        exportPath = UserDefaults.standard.string(forKey: userDefaultsKey) ?? defaultPath
        checkLoginStatus(updateStatus: true)
    }

    var progressValue: Double {
        guard progressTotal > 0 else { return 0 }
        return min(max(progressCurrent / progressTotal, 0), 1)
    }

    var menuBarTitle: String {
        if isRunning {
            return "N₂O \(Int(progressValue * 100))%"
        }
        return "N₂O"
    }

    var combinedStatusLine: String {
        let auth = isLoggedIn ? "Logged in" : "Not logged in"
        return "\(auth) · \(status)"
    }

    private func runCommand(_ launchPath: String, _ args: [String], cwd: String? = nil) -> (Int32, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: launchPath)
        p.arguments = args
        if let cwd {
            p.currentDirectoryURL = URL(fileURLWithPath: cwd)
        }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        do {
            try p.run()
            p.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return (p.terminationStatus, String(decoding: data, as: UTF8.self))
        } catch {
            return (1, "\(error)")
        }
    }

    private func environmentReady() -> Bool {
        let fm = FileManager.default
        if !fm.isExecutableFile(atPath: pythonPath) {
            status = "Python environment not found"
            return false
        }
        if !fm.isExecutableFile(atPath: fullSyncScriptPath) {
            status = "Sync pipeline script not found"
            return false
        }
        return true
    }

    func checkLoginStatus(updateStatus: Bool = false) {
        if !environmentReady() {
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let probe = "from notebooklm_tools.core.auth import AuthManager, load_cached_tokens; from notebooklm_tools.utils.config import get_config; p=get_config().auth.default_profile; ok=AuthManager(p).profile_exists() or (load_cached_tokens() is not None); print('LOGGED_IN' if ok else 'NOT_LOGGED_IN')"
            let (_, out) = self.runCommand(self.pythonPath, ["-c", probe], cwd: self.projectRoot)
            let logged = out.contains("LOGGED_IN")
            DispatchQueue.main.async {
                self.isLoggedIn = logged
                if updateStatus && !self.isRunning {
                    self.status = logged ? "Ready" : "Please login"
                }
            }
        }
    }

    private func startLoginPolling() {
        loginPollTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .userInitiated))
        var ticks = 0
        timer.schedule(deadline: .now() + .seconds(2), repeating: .seconds(2))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            ticks += 1
            let probe = "from notebooklm_tools.core.auth import AuthManager, load_cached_tokens; from notebooklm_tools.utils.config import get_config; p=get_config().auth.default_profile; ok=AuthManager(p).profile_exists() or (load_cached_tokens() is not None); print('LOGGED_IN' if ok else 'NOT_LOGGED_IN')"
            let (_, out) = self.runCommand(self.pythonPath, ["-c", probe], cwd: self.projectRoot)
            let logged = out.contains("LOGGED_IN")
            DispatchQueue.main.async {
                self.isLoggedIn = logged
                if logged {
                    self.status = "Login complete"
                    self.loginPollTimer?.cancel()
                    self.loginPollTimer = nil
                }
            }
            if ticks >= 90 {
                DispatchQueue.main.async {
                    if !self.isLoggedIn {
                        self.status = "Login not detected"
                    }
                    self.loginPollTimer?.cancel()
                    self.loginPollTimer = nil
                }
            }
        }
        loginPollTimer = timer
        timer.resume()
    }

    func login() {
        if !environmentReady() {
            return
        }
        let cmd = "cd \"\(projectRoot)\" && \"\(projectRoot)/Obsidian_Transfer_venv/bin/nlm\" login"
        let escaped = cmd
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let osaScript = "tell application \"Terminal\" to do script \"\(escaped)\""
        let (code, _) = runCommand("/usr/bin/osascript", ["-e", osaScript])
        if code == 0 {
            status = "Complete login in Terminal"
            startLoginPolling()
        } else {
            status = "Unable to open Terminal"
        }
    }

    func choosePath() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Set Path"
        panel.directoryURL = URL(fileURLWithPath: exportPath)
        if panel.runModal() == .OK, let url = panel.url {
            exportPath = url.path
            UserDefaults.standard.set(exportPath, forKey: userDefaultsKey)
            status = "Path updated"
        }
    }

    func syncButtonTapped() {
        if isRunning {
            confirmStopSync()
        } else {
            sync()
        }
    }

    private func confirmStopSync() {
        let alert = NSAlert()
        alert.messageText = "Stop full sync?"
        alert.informativeText = "Sync + chat export is running. Do you want to stop it?"
        alert.addButton(withTitle: "Stop")
        alert.addButton(withTitle: "Continue")
        alert.alertStyle = .warning
        if alert.runModal() == .alertFirstButtonReturn {
            stopSync()
        }
    }

    func stopSync() {
        guard let p = process else { return }
        if p.isRunning {
            userStoppedSync = true
            p.terminate()
            DispatchQueue.global().asyncAfter(deadline: .now() + 2.0) {
                if p.isRunning {
                    p.interrupt()
                }
            }
        }
        status = "Sync stopped"
        isRunning = false
    }

    func quitApp() {
        if isRunning {
            stopSync()
        }
        NSApp.terminate(nil)
    }

    private func handleOutputChunk(_ text: String) {
        outputCarry += text
        while let range = outputCarry.range(of: "\n") {
            let line = String(outputCarry[..<range.lowerBound])
            outputCarry = String(outputCarry[range.upperBound...])
            parseOutputLine(line)
        }
    }

    private func parseOutputLine(_ line: String) {
        if line.hasPrefix("[PHASE] sync-start") {
            DispatchQueue.main.async {
                self.status = "Syncing notebook data..."
                self.progressCurrent = 0
                self.progressTotal = max(self.progressTotal, 1)
            }
            return
        }

        if line.hasPrefix("[PHASE] export-start") {
            DispatchQueue.main.async {
                self.status = "Exporting Antigravity chats..."
                self.progressCurrent = 0
                self.progressTotal = max(self.progressTotal, 1)
            }
            return
        }

        if line.hasPrefix("[INFO] Found") {
            if let r = line.range(of: "syncing ") {
                let tail = line[r.upperBound...]
                let num = tail.prefix { $0.isNumber }
                if let total = Double(num), total > 0 {
                    DispatchQueue.main.async {
                        self.progressTotal = total
                        self.progressCurrent = 0
                        self.status = "Syncing notebook data..."
                    }
                }
                return
            }

            if let m = line.range(of: "Found ") {
                let tail = line[m.upperBound...]
                let num = tail.prefix { $0.isNumber }
                if let total = Double(num), total > 0 {
                    DispatchQueue.main.async {
                        self.progressTotal = total
                        self.progressCurrent = 0
                        if self.status.contains("Exporting") {
                            self.status = "Exporting Antigravity chats..."
                        }
                    }
                }
            }
            return
        }

        if line.hasPrefix("[PROGRESS]") {
            let parts = line.split(separator: " ")
            if parts.count >= 2 {
                let frac = parts[1].split(separator: "/")
                if frac.count == 2,
                   let cur = Double(frac[0]),
                   let total = Double(frac[1]), total > 0 {
                    DispatchQueue.main.async {
                        self.progressCurrent = cur
                        self.progressTotal = total
                        if self.status.contains("Exporting") {
                            self.status = "Exporting \(Int(cur))/\(Int(total))"
                        } else {
                            self.status = "Syncing \(Int(cur))/\(Int(total))"
                        }
                    }
                }
            }
            return
        }

        if line.hasPrefix("[DONE]") {
            DispatchQueue.main.async {
                self.progressCurrent = self.progressTotal
            }
        }
    }

    private func sync() {
        guard !isRunning else { return }
        if !environmentReady() {
            return
        }

        var isDir: ObjCBool = false
        if !FileManager.default.fileExists(atPath: exportPath, isDirectory: &isDir) || !isDir.boolValue {
            status = "Invalid vault path"
            return
        }

        isRunning = true
        userStoppedSync = false
        status = "Starting full sync..."
        progressCurrent = 0
        progressTotal = 1
        outputCarry = ""

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        p.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
        p.arguments = [
            fullSyncScriptPath,
            "--vault-root", exportPath,
            "--include-source-content",
            "--sync-images",
            "--skip-unchanged-notebooks",
            "--overwrite-changed-notebook",
            "--max-source-chars", "0",
            "--clean-markdown"
        ]

        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            guard let self else { return }
            let data = handle.availableData
            if data.isEmpty { return }
            let text = String(decoding: data, as: UTF8.self)
            self.handleOutputChunk(text)
        }

        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self else { return }
                pipe.fileHandleForReading.readabilityHandler = nil
                self.process = nil
                self.isRunning = false
                if self.userStoppedSync {
                    self.userStoppedSync = false
                    self.status = "Sync stopped"
                } else {
                    self.status = proc.terminationStatus == 0 ? "Full sync complete" : "Sync failed (\(proc.terminationStatus))"
                }
            }
        }

        do {
            try p.run()
            process = p
        } catch {
            isRunning = false
            status = "Failed to start"
        }
    }
}

struct GlassButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 9)
            .foregroundStyle(.white)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [Color.white.opacity(0.22), Color.white.opacity(0.07)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .stroke(Color.white.opacity(0.15), lineWidth: 0.8)
                    )
            )
            .shadow(color: .black.opacity(0.10), radius: 4, x: 0, y: 1.5)
            .scaleEffect(configuration.isPressed ? 0.965 : 1.0)
            .opacity(configuration.isPressed ? 0.78 : 0.92)
            .offset(y: configuration.isPressed ? 0.5 : 0)
            .animation(.easeOut(duration: 0.11), value: configuration.isPressed)
    }
}

struct MenuContentView: View {
    @ObservedObject var controller: SyncController

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("NotebookLM")
                    .font(.system(size: 11, weight: .semibold))
                Spacer()
                Text("Obsidian")
                    .font(.system(size: 11, weight: .semibold))
            }

            ProgressView(value: controller.progressValue)
                .progressViewStyle(.linear)

            Text(controller.combinedStatusLine)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(1)

            HStack(spacing: 8) {
                Button("Login") { controller.login() }
                    .frame(maxWidth: .infinity)
                Button("Set Path") { controller.choosePath() }
                    .frame(maxWidth: .infinity)
                Button(controller.isRunning ? "Stop" : "Sync") { controller.syncButtonTapped() }
                    .frame(maxWidth: .infinity)
                Button("Quit") { controller.quitApp() }
                    .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(GlassButtonStyle())
        }
        .padding(12)
        .frame(width: 372)
    }
}

@main
struct NotebookSyncApp: App {
    @StateObject private var controller = SyncController()

    var body: some Scene {
        MenuBarExtra(controller.menuBarTitle) {
            MenuContentView(controller: controller)
        }
        .menuBarExtraStyle(.window)
    }
}
