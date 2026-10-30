[app]
# python-for-android 版本（默认 master 会用 Python 3.14，与 Kivy 2.3.1 不兼容）
p4a.branch = v2024.01.21

# 应用信息
title = 背单词
package.name = beidanci
package.domain = org.mynotes

source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,otf,json,csv,txt,spec
source.include_patterns = assets/*
source.exclude_dirs = tests,bin,__pycache__,screenshots,.github

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/icon.png

version = 3.1.0

# 依赖：Kivy + requests（联网取音频）+ pyjnius（安卓 MediaPlayer 兜底）
requirements = python3,kivy==2.3.1,requests,pyjnius

orientation = landscape
fullscreen = 1

# 安卓权限：联网下载音频；读写外部存储（words.csv / READ 与 Syncthing 共享目录）
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = apk
android.debug_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
