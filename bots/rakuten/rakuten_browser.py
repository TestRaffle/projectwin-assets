"""
楽天市場 Browser モード
- クッキーが保存されていればそれを読み込んでログイン状態を復元
- ログインされていなければログイン処理を実行
- ログイン成功後、指定URLにアクセス
- ユーザーが自由に操作可能（Stopボタンが押されるまで待機）
"""

import argparse
import json
import os
import sys
import time
import re
import random
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# グローバルAPP_DIR（GUIから設定される）
APP_DIR = None


class RakutenBrowser:
    """楽天市場 Browserモードクラス"""
    
    # 楽天のベース情報
    BASE_URL = "https://www.rakuten.co.jp"
    LOGIN_URL = "https://www.rakuten.co.jp"
    
    def __init__(self, task_data, settings=None):
        """
        初期化
        
        Args:
            task_data: Excelから読み込んだ全カラムのデータ（辞書）
            settings: GUIから渡される設定（辞書）
        """
        self.task_data = task_data
        self.settings = settings or {}
        
        # よく使うデータを取り出し
        self.profile = task_data.get("Profile", "")
        self.site = task_data.get("Site", "")
        self.mode = task_data.get("Mode", "")
        self.url = task_data.get("URL", "") or self.BASE_URL
        self.proxy = task_data.get("Proxy", "")
        self.headless = task_data.get("Headless", False)
        
        # ログイン情報
        self.login_id = task_data.get("Loginid", "")
        self.login_pass = task_data.get("Loginpass", "")
        
        # 設定ディレクトリを取得（exe化対応）
        self._settings_dir = self._get_settings_dir()
        
        # ブラウザ関連
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        # クッキー保存先ディレクトリ
        self.cookies_dir = self._get_cookies_dir()
        
        # ストップ制御（GUIから設定される）
        self._worker = None  # GUIのワーカー参照
        self._stop_requested = False  # ストップフラグ
        self._browser_closed = False  # ブラウザ閉じ検知
    
    def _get_settings_dir(self):
        """設定ディレクトリを取得（exe化対応）"""
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            settings_dir = APP_DIR / "_internal" / "settings"
            if settings_dir.exists():
                return settings_dir
            settings_dir = APP_DIR / "settings"
            if settings_dir.exists():
                return settings_dir
        
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
            settings_dir = base_dir / "_internal" / "settings"
            if settings_dir.exists():
                return settings_dir
            return base_dir / "settings"
        else:
            # 開発環境: カレントディレクトリを基準にする
            import os
            base_dir = Path(os.getcwd())
            settings_dir = base_dir / "_internal" / "settings"
            if settings_dir.exists():
                return settings_dir
            return base_dir / "settings"
    
    def _get_cookies_dir(self):
        """クッキーディレクトリを取得"""
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            cookies_dir = APP_DIR / "_internal" / "cookies" / "Rakuten"
            cookies_dir.mkdir(parents=True, exist_ok=True)
            return cookies_dir
        
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
            cookies_dir = base_dir / "_internal" / "cookies" / "Rakuten"
        else:
            # 開発環境: カレントディレクトリを基準にする
            import os
            base_dir = Path(os.getcwd())
            cookies_dir = base_dir / "_internal" / "cookies" / "Rakuten"
        
        cookies_dir.mkdir(parents=True, exist_ok=True)
        return cookies_dir
    
    def _get_cookie_path(self):
        """クッキーファイルパスを取得（Loginidベース）"""
        return self.cookies_dir / f"{self.login_id}.json"
    
    def random_sleep(self, min_sec=1, max_sec=3):
        """ランダムな待機時間"""
        time.sleep(random.uniform(min_sec, max_sec))
    
    def start_browser(self):
        """ブラウザを起動"""
        print("Starting browser...")
        
        self.playwright = sync_playwright().start()
        
        # Chromeのパスを探す
        browser_path = None
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                browser_path = path
                print(f"[Browser] Using Chrome: {path}")
                break
        
        # プロキシ設定
        proxy_config = None
        if self.proxy:
            parts = self.proxy.split(":")
            if len(parts) >= 2:
                proxy_config = {
                    "server": f"http://{parts[0]}:{parts[1]}"
                }
                if len(parts) >= 4:
                    proxy_config["username"] = parts[2]
                    proxy_config["password"] = parts[3]
                print(f"[Proxy] Using: {parts[0]}:{parts[1]}")
        
        launch_options = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-extensions",
                "--disable-popup-blocking",
                "--disable-notifications",
                "--disable-gpu",
                "--window-size=1280,1280",
            ]
        }
        
        if browser_path:
            launch_options["executable_path"] = browser_path
        else:
            launch_options["channel"] = "chrome"
        
        if proxy_config:
            launch_options["proxy"] = proxy_config
        
        self.browser = self.playwright.chromium.launch(**launch_options)
        
        context_options = {
            "viewport": {"width": 1280, "height": 1280},
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
            "permissions": ["geolocation"],
            "java_script_enabled": True,
        }
        
        self.context = self.browser.new_context(**context_options)
        self.page = self.context.new_page()
        
        # ブラウザ閉じ検知
        self.page.on("close", self._on_page_close)
        
        print("Browser started")
    
    def _on_page_close(self, page):
        """ページが閉じられた時のハンドラ"""
        print("Page closed by user")
        self._browser_closed = True
    
    def close_browser(self):
        """ブラウザを閉じる"""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            print(f"Error closing browser: {e}")
    
    def load_cookies(self):
        """クッキーを読み込む"""
        cookie_path = self._get_cookie_path()
        if cookie_path.exists():
            try:
                with open(cookie_path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                self.context.add_cookies(cookies)
                print(f"Cookies loaded from {cookie_path}")
                return True
            except Exception as e:
                print(f"Failed to load cookies: {e}")
        return False
    
    def save_cookies(self):
        """クッキーを保存"""
        try:
            cookies = self.context.cookies()
            
            # クッキーの有効期限を1年後に延長
            one_year_later = time.time() + (365 * 24 * 60 * 60)
            for cookie in cookies:
                if 'expires' in cookie and cookie['expires'] > 0:
                    cookie['expires'] = one_year_later
            
            cookie_path = self._get_cookie_path()
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f)
            print(f"Cookies saved to {cookie_path}")
            return True
        except Exception as e:
            print(f"Failed to save cookies: {e}")
            return False
    
    def check_login_status(self):
        """ログイン状態をチェック"""
        try:
            print("Checking login status...")
            self.page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=60000)
            self.random_sleep(2, 3)
            
            # 「さん」が表示されていればログイン済み
            san_element = self.page.locator('div.title--2tRgg:has-text("さん")').first
            if san_element.is_visible(timeout=5000):
                print("Already logged in")
                return True
            
            return False
        except Exception as e:
            print(f"Login check error: {e}")
            return False
    
    def do_login(self):
        """ログイン処理"""
        try:
            print("Starting login process...")
            
            # トップページにアクセス
            self.page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=60000)
            self.random_sleep(2, 3)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # ログインボタンをクリック
            print("\x00STATUS:Clicking Login", flush=True)
            try:
                login_button = self.page.locator('a[aria-label="ログイン"]')
                if login_button.is_visible(timeout=10000):
                    login_button.click()
                    print("Login button clicked")
                else:
                    print("Login button not found")
                    return False
            except Exception as e:
                print(f"Login button error: {e}")
                return False
            
            self.random_sleep(2, 3)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # メールアドレス入力
            print("\x00STATUS:Entering Email", flush=True)
            try:
                email_input = self.page.wait_for_selector('input[name="username"], input#user_id', timeout=15000)
                if email_input:
                    email_input.click()
                    self.random_sleep(0.3, 0.5)
                    email_input.fill(self.login_id)
                    print(f"Email entered: {self.login_id}")
                else:
                    print("Email input not found")
                    return False
            except Exception as e:
                print(f"Email input error: {e}")
                return False
            
            self.random_sleep(1, 2)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # 次へボタンをクリック
            print("\x00STATUS:Clicking Next", flush=True)
            try:
                next_button = self.page.locator('div[id="cta001"]')
                if next_button.is_visible(timeout=5000):
                    next_button.click()
                    print("Next button clicked")
                else:
                    print("Next button not found")
                    return False
            except Exception as e:
                print(f"Next button error: {e}")
                return False
            
            self.random_sleep(2, 3)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # パスワード入力
            print("\x00STATUS:Entering Password", flush=True)
            try:
                password_input = self.page.wait_for_selector('input[name="password"], input#password_current', timeout=15000)
                if password_input:
                    password_input.click()
                    self.random_sleep(0.3, 0.5)
                    password_input.fill(self.login_pass)
                    print("Password entered")
                else:
                    print("Password input not found")
                    return False
            except Exception as e:
                print(f"Password input error: {e}")
                return False
            
            self.random_sleep(1, 2)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # ログインボタン（次へ）をクリック
            print("\x00STATUS:Submitting Login", flush=True)
            try:
                submit_button = self.page.locator('div[id="cta011"]')
                if submit_button.is_visible(timeout=5000):
                    submit_button.click()
                    print("Submit button clicked")
                else:
                    print("Submit button not found")
                    return False
            except Exception as e:
                print(f"Submit button error: {e}")
                return False
            
            self.random_sleep(3, 5)
            
            if self._stop_requested or self._browser_closed:
                return False
            
            # ログイン成功確認
            print("\x00STATUS:Verifying Login", flush=True)
            try:
                # 「さん」が表示されていればログイン成功
                san_element = self.page.locator('div.title--2tRgg:has-text("さん")').first
                if san_element.is_visible(timeout=15000):
                    print("Login successful!")
                    return True
                else:
                    print("Login verification failed")
                    return False
            except Exception as e:
                print(f"Login verification error: {e}")
                return False
            
        except Exception as e:
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def navigate_to_target_url(self):
        """目的URLにアクセス"""
        try:
            target_url = self.url if self.url else self.BASE_URL
            print(f"Navigating to: {target_url}")
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            self.random_sleep(2, 3)
            return True
        except Exception as e:
            print(f"Navigation error: {e}")
            return False
    
    def wait_for_user(self):
        """ユーザー操作を待機（ストップボタンが押されるまで）"""
        print("Waiting for user... (Stop button to finish)")
        
        while not self._stop_requested and not self._browser_closed:
            try:
                time.sleep(1)
                
                if self.page and not self.page.is_closed():
                    continue
                else:
                    print("Browser was closed by user")
                    break
            except Exception as e:
                print(f"Wait error: {e}")
                break
        
        print("User operation finished")
    
    def run(self):
        """メイン実行
        
        Returns:
            tuple: (success: bool, error_status: str or None)
        """
        import traceback
        
        try:
            print("=" * 50)
            print(f"Site: {self.site} Mode: {self.mode}")
            print("=" * 50)
            
            if self._stop_requested:
                return False, "Stopped"
            
            # ブラウザ起動
            print("\x00STATUS:Starting Task", flush=True)
            try:
                self.start_browser()
            except Exception as e:
                print(f"Browser start failed: {e}")
                return False, "Failed Browser"
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            self.load_cookies()
            
            print("\x00STATUS:Checking Login", flush=True)
            login_status = self.check_login_status()
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            if not login_status:
                print("\x00STATUS:Logging In", flush=True)
                login_result = self.do_login()
                if not login_result:
                    return False, "Login Failed"
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            # クッキー保存
            self.save_cookies()
            
            # 目的URLにアクセス
            print("\x00STATUS:Navigating", flush=True)
            if not self.navigate_to_target_url():
                return False, "Failed Navigation"
            
            # ブラウジングモード
            print("\x00STATUS:Browsing", flush=True)
            print("Navigation successful!")
            
            # ユーザー操作待機
            self.wait_for_user()
            
            # 最後にクッキー保存
            self.save_cookies()
            
            if self._stop_requested:
                return True, None
            
            if self._browser_closed:
                return False, "Browser Closed"
            
            return True, None
            
        except Exception as e:
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            print(f"Error in run(): {e}")
            traceback.print_exc()
            return False, "Failed Unknown"
        finally:
            self.close_browser()


def main():
    import traceback
    
    parser = argparse.ArgumentParser(description="Rakuten Browser Mode Bot")
    parser.add_argument("--task-data", required=True, help="Path to task data JSON file")
    
    args = parser.parse_args()
    
    print(f"Task data file: {args.task_data}")
    
    try:
        with open(args.task_data, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        print(f"Task data loaded successfully")
    except Exception as e:
        print(f"Failed to load task data: {e}")
        traceback.print_exc()
        return
    
    try:
        bot = RakutenBrowser(task_data)
        success, error_status = bot.run()
        
        if error_status:
            print(f"ERROR:{error_status}")
        
        print(f"Bot finished with success={success}")
    except Exception as e:
        print(f"Bot execution error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()