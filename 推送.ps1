# 推送 Kivy 背单词仓库到 GitHub（Windows PowerShell）
# 用法：右键本文件 → 使用 PowerShell 运行；或 powershell -ExecutionPolicy Bypass -File 推送.ps1
param(
    [string]$RepoUrl = "",
    [string]$GitHubUser = "",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path   # 本文件就在工程根目录
$work = Split-Path -Parent $proj                          # workspace

# 1. 找 git：优先 PATH，其次工作区附带的便携版 MinGit
$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) {
    $cand = Join-Path $work "tools\MinGit\cmd\git.exe"
    if (Test-Path $cand) { $git = $cand }
}
if (-not $git) {
    Write-Host "没找到 git。请安装 Git for Windows，或用 GitHub Desktop 推送。" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $proj ".git"))) {
    Write-Host "工程目录缺少 .git：$proj" -ForegroundColor Red
    exit 1
}
Set-Location $proj

# 2. 询问仓库地址
if (-not $RepoUrl) {
    Write-Host "请粘贴你在 GitHub 新建的空仓库地址，例如：" -ForegroundColor Cyan
    Write-Host "  https://github.com/你的用户名/beidanci.git" -ForegroundColor DarkGray
    $RepoUrl = Read-Host "仓库地址"
}
$RepoUrl = $RepoUrl.Trim()
if ($RepoUrl -notmatch "^(https://|git@)") {
    Write-Host "地址看起来不对：$RepoUrl" -ForegroundColor Red
    exit 1
}

# 3. GitHub 已不接受账号密码，https 推送需要 Personal Access Token
$pushUrl = $RepoUrl
if (-not $GitHubUser -and $RepoUrl -match "github\.com[:/]([^/]+)/(.+?)(\.git)?$") {
    $GitHubUser = $Matches[1]
}
if (-not $Token -and $RepoUrl -match "^https://") {
    Write-Host ""
    Write-Host "GitHub 推送需要 Personal Access Token（不是账号密码）：" -ForegroundColor Cyan
    Write-Host "  打开 https://github.com/settings/tokens → Generate new token (classic) → 勾选 repo → 生成后复制" -ForegroundColor DarkGray
    $sec = Read-Host "粘贴 token（输入时不显示；直接回车则跳过）" -AsSecureString
    $Token = [System.Net.NetworkCredential]::new("", $sec).Password
}
if ($Token -and $GitHubUser -and $RepoUrl -match "^https://") {
    $repoName = ($RepoUrl -split "/")[-1]
    $pushUrl = "https://${GitHubUser}:${Token}@github.com/${GitHubUser}/${repoName}"
}

# 4. 设置 remote 并推送
& $git remote remove origin 2>$null
& $git remote add origin $pushUrl
Write-Host ""
Write-Host "推送中：$($RepoUrl)" -ForegroundColor Cyan
& $git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "推送失败，可改用 GitHub Desktop：" -ForegroundColor Yellow
    Write-Host "  Add local repository → 选本目录 → Publish repository" -ForegroundColor Yellow
    exit $LASTEXITCODE
}

# 5. 把带 token 的地址换回干净地址，避免 token 留在本地配置
& $git remote set-url origin $RepoUrl

Write-Host ""
Write-Host "推送成功！接下来：" -ForegroundColor Green
Write-Host "  1) 打开仓库页面 → Actions → build-apk → Run workflow"
Write-Host "  2) 等 20~40 分钟，在该次运行底部 Artifacts 下载 beidanci-apk"
Write-Host "  3) 解压得到 APK，拷到平板安装"
