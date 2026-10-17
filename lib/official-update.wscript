// Placeholders are filled by official-update.js. Quit the official client, run the downloaded installer, then reopen.
var exe = __EXE_JSON__;
var installer = __INSTALLER_JSON__;
var resources = __RESOURCES_JSON__;
var installDir = __INSTALL_DIR_JSON__;
if (installDir.length > 3) installDir = installDir.replace(/[\\\/]+$/, '');
var logPath = __LOG_JSON__;
var fso = new ActiveXObject('Scripting.FileSystemObject');
var sh = new ActiveXObject('WScript.Shell');
var wmi = GetObject('winmgmts:\\\\.\\root\\cimv2');
function z(n) { return (n < 10 ? '0' : '') + n; }
function stamp() { var d = new Date(); return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate()) + 'T' + z(d.getHours()) + ':' + z(d.getMinutes()) + ':' + z(d.getSeconds()); }
function log(m) { var f = fso.OpenTextFile(logPath, 8, true); f.WriteLine(stamp() + ' ' + m); f.Close(); }
function errText(e) { return e && e.message ? e.message : String(e); }
function tempDir() {
  var d = '';
  try { d = String(fso.GetSpecialFolder(2).Path || ''); } catch (e1) {}
  if (!d) { try { d = String(sh.ExpandEnvironmentStrings('%TEMP%') || ''); } catch (e2) {} }
  if (!d || d.indexOf('%') >= 0 || d.length < 4) d = 'C:\\Windows\\Temp';
  return d;
}
// The installer renames the install directory to <name>.old-{GUID}. Windows refuses that
// rename while any process still has the directory as its current directory
// (ERROR_SHARING_VIOLATION / 32), and this helper used to inherit exactly that current
// directory from the app. Leave it before touching anything.
function leaveInstallDir() {
  var d = tempDir();
  try { sh.CurrentDirectory = d; } catch (e3) { return 'failed'; }
  return d;
}
function sameDrive(a, b) { return String(a).substr(0, 2).toLowerCase() === String(b).substr(0, 2).toLowerCase(); }
function samePath(a, b) { return String(a || '').replace(/\//g, '\\').toLowerCase() === String(b || '').replace(/\//g, '\\').toLowerCase(); }
function pids() { var out = []; var e = new Enumerator(wmi.ExecQuery("SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = 'DeepSeek Harness.exe'")); for (; !e.atEnd(); e.moveNext()) { var p = e.item(); if (samePath(p.ExecutablePath, exe)) out.push(p.ProcessId); } return out; }
function fileSize(fp) { if (!fso.FileExists(fp)) return -1; return fso.GetFile(fp).Size; }
function fileStamp(fp) { if (!fso.FileExists(fp)) return ''; return String(fso.GetFile(fp).DateLastModified); }
// Never delete a tree with a recursive API that follows reparse points. The patched unpacked
// app dir contains resources\app\runtime as a junction whose target is an absolute path under
// the install directory; after an update that target is the freshly installed runtime. The
// installer's own cleanup of its <name>.old-{GUID} backup already demonstrated what following
// such a link does - it emptied the new resources\runtime and the client could not start.
// Scripting.FileSystemObject does follow junctions, Node's rmSync unlinks them instead.
function removeTreeSafe(target) {
  if (!fso.FolderExists(target)) return true;
  var node = resources + '\\runtime\\primary-runtime\\dependencies\\node\\bin\\node.exe';
  if (!fso.FileExists(node)) { log('cleanup-node-missing'); return false; }
  var js = tempDir() + '\\dsh-purge-rm-' + (new Date().getTime()) + '.js';
  try {
    var f = fso.CreateTextFile(js, true);
    f.WriteLine("require('fs').rmSync(process.argv[2], { recursive: true, force: true });");
    f.Close();
    sh.Run('"' + node + '" "' + js + '" "' + target + '"', 0, true);
    try { fso.DeleteFile(js, true); } catch (e4) {}
  } catch (e5) { log('cleanup ' + errText(e5)); return false; }
  return !fso.FolderExists(target);
}
log('update-begin');
log('cwd ' + leaveInstallDir());
WScript.Sleep(800);
var list = pids();
log('pids ' + list.join(','));
for (var i = 0; i < list.length; i++) sh.Run('taskkill.exe /F /PID ' + list[i], 0, true);
var deadline = new Date().getTime() + 20000;
var left = list;
while (new Date().getTime() < deadline) { left = pids(); if (left.length === 0) break; WScript.Sleep(200); }
log('left ' + left.length);
var asar = resources + '\\app.asar';
var bak = asar + '.bak';
var appDir = resources + '\\app';
var movedApp = false;
var stashRoot = '';
var stash = '';
var prev = '';
if (fso.FolderExists(appDir)) {
  // Preferred: move the patched dir completely OUT of the install tree, so the installer's
  // backup-delete cannot reach the junction it contains. Only a same-volume move is a plain
  // rename; across volumes fall back to the in-tree rename (deletion is still reparse-safe).
  if (sameDrive(appDir, tempDir())) {
    var candidate = tempDir() + '\\dsh-purge-app-stash-' + (new Date().getTime());
    for (var n = 0; n < 40; n++) {
      try {
        if (!fso.FolderExists(candidate)) fso.CreateFolder(candidate);
        fso.MoveFolder(appDir, candidate + '\\app');
        movedApp = true;
        stashRoot = candidate;
        stash = candidate + '\\app';
        log('stashed-app ' + stash);
        break;
      } catch (stashErr) { log('stash-app ' + errText(stashErr)); WScript.Sleep(250); }
    }
  }
  if (!movedApp) {
    prev = appDir + '.dshpurge-prev';
    if (fso.FolderExists(prev)) prev = appDir + '.dshpurge-prev-' + (new Date().getTime());
    for (var n2 = 0; n2 < 40; n2++) {
      try { fso.MoveFolder(appDir, prev); movedApp = true; log('moved-app'); break; }
      catch (moveErr) { log('move-app ' + errText(moveErr)); WScript.Sleep(250); }
    }
  }
}
var copiedAsar = false;
if (!fso.FileExists(asar) && fso.FileExists(bak)) {
  try { fso.CopyFile(bak, asar, true); copiedAsar = true; log('restored-asar'); }
  catch (restoreErr) { log('restore-asar ' + errText(restoreErr)); }
}
var exeBeforeSize = fileSize(exe);
var exeBeforeStamp = fileStamp(exe);
var asarBeforeSize = fileSize(asar);
function runInstaller(updated) {
  var args = updated ? ' --updated /S /D=' : ' /S /D=';
  return sh.Run('"' + installer + '"' + args + installDir, 0, true);
}
var code = runInstaller(true);
log('installer ' + code);
var exeChanged = fileSize(exe) !== exeBeforeSize || fileStamp(exe) !== exeBeforeStamp;
var asarChanged = fileSize(asar) !== asarBeforeSize;
var ok = exeChanged || asarChanged;
log('changed exe=' + exeChanged + ' asar=' + asarChanged);
if (!ok) {
  code = runInstaller(false);
  log('installer-plain ' + code);
  exeChanged = fileSize(exe) !== exeBeforeSize || fileStamp(exe) !== exeBeforeStamp;
  asarChanged = fileSize(asar) !== asarBeforeSize;
  ok = exeChanged || asarChanged;
  log('changed-plain exe=' + exeChanged + ' asar=' + asarChanged);
}
if (!ok) {
  if (copiedAsar && fso.FileExists(asar)) {
    try { fso.DeleteFile(asar, true); log('rehid-asar'); } catch (hideErr) { log('rehid-asar ' + errText(hideErr)); }
  }
  // A concurrent unpack helper may have recreated resources\app. On failure, move the patched dir back.
  if (movedApp) {
    if (stash) {
      if (fso.FolderExists(appDir) && removeTreeSafe(appDir)) log('cleared-recreated-app');
      if (!fso.FolderExists(appDir)) {
        try { fso.MoveFolder(stash, appDir); log('restored-app'); } catch (backErr) { log('restored-app ' + errText(backErr)); }
      }
      if (!fso.FolderExists(stash) && fso.FolderExists(stashRoot)) {
        try { fso.DeleteFolder(stashRoot, true); } catch (rootErr) {}
      }
    } else if (prev && fso.FolderExists(prev)) {
      if (fso.FolderExists(appDir) && removeTreeSafe(appDir)) log('cleared-recreated-app');
      if (!fso.FolderExists(appDir)) {
        try { fso.MoveFolder(prev, appDir); log('restored-app'); } catch (backErr2) { log('restored-app ' + errText(backErr2)); }
      }
    }
  }
  try { sh.Environment('PROCESS').Remove('ELECTRON_RUN_AS_NODE'); } catch (ignore) {}
  sh.Run('"' + exe + '"', 1, false);
  log('started-old');
} else {
  if (!movedApp && fso.FolderExists(appDir)) log('move-app-failed');
  var drop = '';
  if (stash && fso.FolderExists(stash)) drop = stashRoot;
  else if (prev && fso.FolderExists(prev)) drop = prev;
  if (drop) {
    if (removeTreeSafe(drop)) log('dropped-old-app');
    else log('stash-kept ' + drop);
  }
  // The installer ships resources\runtime, but the client dies at startup without it. Say so
  // instead of silently starting a build that cannot load its skills.
  var runtimeOk = fso.FileExists(resources + '\\runtime\\versions.json');
  log('runtime ' + (runtimeOk ? 'ok' : 'MISSING'));
  try {
    if (runtimeOk && fso.FileExists(resources + '\\dsh-purge-runtime-missing')) fso.DeleteFile(resources + '\\dsh-purge-runtime-missing', true);
  } catch (clearWarnErr) {}
  if (!runtimeOk) {
    try {
      var warn = fso.CreateTextFile(resources + '\\dsh-purge-runtime-missing', true);
      warn.WriteLine('resources\\runtime is missing after install');
      warn.Close();
    } catch (warnErr) { log('runtime-marker ' + errText(warnErr)); }
  }
  try {
    var marker = fso.CreateTextFile(resources + '\\dsh-purge-reapply-asar', true);
    marker.WriteLine('1');
    marker.Close();
    log('marker');
  } catch (markerErr) { log('marker ' + errText(markerErr)); }
  try { sh.Environment('PROCESS').Remove('ELECTRON_RUN_AS_NODE'); } catch (ignore2) {}
  sh.Run('"' + exe + '"', 1, false);
  log('started');
}
