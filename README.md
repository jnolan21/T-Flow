## Setup

1. Install [Git LFS](https://git-lfs.com/) then clone normally:
```bash
   git lfs install
   git clone <repo-url>
```

2. Install Python dependencies:
```bash
   pip install -r requirements.txt
```

3. Make sure Java 11+ is installed (`java -version`)

4. Set your Android SDK path in `src/run_flowdroid.py` if it differs from `~/Library/Android/sdk/platforms`