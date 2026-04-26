# GitHub Pages サイト化プロンプト

## 依頼文

以下のものを GitHub Pages で公開できる形にしてください。

【対象】
（※ ここに対象を書く。例: Pythonスクリプト / 既存のHTMLファイル / データ可視化ツール など）

---

### 成果物として作るファイル

| ファイル | 役割 |
|---|---|
| `index.html` | 公開するスタンドアロン HTML |
| `requirements.txt` | Python 依存ライブラリ（Python を使う場合） |
| `.gitignore` | Python キャッシュ・DS_Store・`.env` 等を除外 |
| `.github/workflows/deploy.yml` | GitHub Actions 自動デプロイ |
| `update.sh` | ワンコマンド手動更新スクリプト |
| `更新.app` | ダブルクリックで更新できる macOS アプリ |

---

### 1. スタンドアロン HTML 化

- CSS・JS はすべて HTML 内にインライン
- CDN ライブラリは `<script src>` で読み込んでよい
- ブラウザで HTML ファイルを直接開けば動く状態にする

---

### 2. iPhone Safari 対応

```html
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
```
```css
html { -webkit-text-size-adjust: 100%; overflow-x: hidden; }
body { overflow-x: hidden; -webkit-overflow-scrolling: touch; }
.sticky-el { position: -webkit-sticky; position: sticky; }
```

---

### 3. 💾 保存ボタン

HTML 内に保存ボタンを追加し、タップ1回でファイルをダウンロードできるようにする。

```js
function savePage() {
  const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob), download: 'index.html'
  });
  a.click();
  URL.revokeObjectURL(a.href);
}
```

---

### 4. Git 初期化 → GitHub プッシュ

```bash
git init
# .gitignore 作成（__pycache__/ *.pyc .DS_Store .env *.icloud）
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

---

### 5. GitHub Actions（`.github/workflows/deploy.yml`）

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5      # Python を使う場合のみ
        with: { python-version: '3.12', cache: pip }
      - run: pip install -r requirements.txt  # Python を使う場合のみ
      - run: python generate.py              # HTML 生成スクリプトがある場合のみ
      - name: Prepare site
        run: |
          mkdir _site
          cp index.html _site/index.html    # ファイル名に合わせて変更
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with: { path: _site }
      - uses: actions/deploy-pages@v4
        id: deploy
```

GitHub の Settings → Pages → Source を **GitHub Actions** に変更する。

公開 URL: `https://<user>.github.io/<repo>/`

---

### 6. 手動更新スクリプト（`update.sh`）

```bash
#!/bin/bash
set -e
python3 generate.py          # HTML を再生成（静的 HTML の場合は不要）
git add index.html           # 更新されたファイル名に合わせる
git commit -m "Update $(date '+%Y-%m-%d %H:%M')"
git push
echo "✅ Done. Pages will update in ~1 min."
```

```bash
chmod +x update.sh
./update.sh   # 実行するだけで更新完了
```

---

### 7. macOS アプリ化（ダブルクリックで更新）

```bash
# AppleScript を書いて .app としてコンパイル
cat > /tmp/updater.applescript << 'EOF'
set workDir to (POSIX path of (path to home folder)) & "path/to/project"
display notification "更新中..." with title "🔄 サイト更新"
try
    do shell script "cd '" & workDir & "' && ./update.sh 2>&1"
    display notification "約1分で反映されます" with title "✅ 更新完了"
on error errMsg
    display alert "エラー" message errMsg as critical
end try
EOF

osacompile -o "更新.app" /tmp/updater.applescript
```

初回は右クリック → 開く で起動。以降はダブルクリックで OK。
