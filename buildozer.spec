[app]
title = Gold SMC Monitor
package.name = goldsmcmonitor
package.domain = org.goldmonitor
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0

requirements = python3,kivy==2.3.0,requests,plyer,pyjnius,certifi,urllib3,idna,charset-normalizer

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,VIBRATE,WAKE_LOCK
android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
