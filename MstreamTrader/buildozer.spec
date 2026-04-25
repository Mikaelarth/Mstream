[app]
title = MstreamTrader
package.name = mstreamtrader
package.domain = com.mstream

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,db
source.include_patterns = kv/*,assets/*,core/*.py,screens/*.py

version = 1.0.0

requirements = python3,kivy==2.3.0

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,VIBRATE,RECEIVE_BOOT_COMPLETED
android.api = 33
android.minapi = 24
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True
android.logcat_filters = *:S python:D

[buildozer]
log_level = 2
warn_on_root = 1
