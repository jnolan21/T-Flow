# T-Flow: Taint Flow Explorer

Interactive visualization of how sensitive data flows through Android applications,
powered by FlowDroid static taint analysis.

## Setup

### Prerequisites
- Python 3.9+
- Java 11+ (`java -version` to verify)
- Android SDK with platforms installed
- Git LFS (`brew install git-lfs` on Mac, or https://git-lfs.com)

### Installation

```bash
git lfs install
git clone https://github.com/jnolan21/T-Flow.git
cd T-Flow
pip install -r requirements.txt
```

### Android SDK Path

T-Flow needs to know where your Android SDK platforms are. Set this environment variable:

```bash
# Mac (default, may already work)
export ANDROID_PLATFORMS=~/Library/Android/sdk/platforms

# Linux
export ANDROID_PLATFORMS=~/Android/Sdk/platforms

# Windows
set ANDROID_PLATFORMS=C:\Users\<you>\AppData\Local\Android\Sdk\platforms
```

## Running the App

```bash
python3 src/graph/graph_dashboard.py
```

Then open your browser to `http://127.0.0.1:8050`.

## Testing with Provided APKs

Several DroidBench benchmark APKs are included for immediate testing:

| APK | Description |
|-----|-------------|
| `data/apks/Callbacks/Button1.apk` | Data leak triggered by button click |
| `data/apks/Callbacks/Button2.apk` | Leak only when buttons clicked in order |
| `data/apks/Callbacks/LocationLeak1.apk` | GPS location leaked via SMS |
| `data/apks/Callbacks/LocationLeak2.apk` | Location leak across lifecycle methods |
| `data/apks/Callbacks/MethodOverride1.apk` | Leak through overridden method |
| `data/apks/Lifecycle/ActivityLifecycle1.apk` | Leak across Activity lifecycle |
| `data/apks/ArraysAndLists/ArrayToString1.apk` | Array data leaked as string |
| `data/apks/GeneralJava/Loop1.apk` | Data leaked inside a loop |
| `data/apks/FieldAndObjectSensitivity/FieldSensitivity3.apk` | Field-sensitive data flow |
| `data/apks/AndroidSpecific/PrivateDataLeak1.apk` | Private data (password) leaked via SMS |

To analyze one, upload it through the UI after launching the app.

## Testing with Your Own APK

You can upload any Android `.apk` file through the UI. T-Flow will run FlowDroid on it
and visualize the resulting taint flows automatically.

**Do you need to modify `SourcesAndSinks.txt`?**

For most APKs, **no** — the included `SourcesAndSinks.txt` covers a comprehensive set of
standard Android privacy sources (device ID, location, contacts, SMS, etc.) and sinks
(network, SMS, logging). This works well for detecting common privacy leaks in any app.

You would only need to customize `SourcesAndSinks.txt` if your APK uses **custom
application-specific** methods as sources or sinks that aren't part of the standard
Android API — for example, a proprietary data collection SDK. In that case, you can add
entries to `FlowDroid-2.15.1/SourcesAndSinks.txt` following the existing format:

```
<com.example.MyClass: java.lang.String getSensitiveData()> -> _SOURCE_
<com.example.MyClass: void sendData(java.lang.String)> -> _SINK_
```