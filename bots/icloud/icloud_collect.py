"""
iCloud Collect モード
- iCloudにログイン
- Hide My Email のアドレス一覧を取得
- txtファイルにエクスポート
"""

import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path


def get_app_dir():
    """アプリのルートディレクトリを取得"""
    if 'APP_DIR' in globals() and globals()['APP_DIR']:
        return globals()['APP_DIR']
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent.parent.parent


APP_DIR = get_app_dir()


class IcloudCollect:
    """iCloud Hide My Email Collectクラス"""
    
    BASE_URL = "https://www.icloud.com"
    
    def __init__(self, task_data, settings=None):
        self.task_data = task_data
        self.settings = settings or {}
        
        # タスクデータから情報取得
        self.loginid = task_data.get("Loginid", "")
        self.loginpass = task_data.get("Loginpass", "")
        self.profile = task_data.get("Profile", "default")
        self.proxy = task_data.get("Proxy", "")
        self.headless = task_data.get("Headless", False)
        
        # ディレクトリ設定
        self.cookies_dir = self._get_cookies_dir()
        self.export_dir = self._get_export_dir()
        
        # ブラウザ関連
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        # 停止フラグ
        self._stop_requested = False
        self._browser_closed = False
        
    def _get_cookies_dir(self):
        """クッキー保存ディレクトリを取得"""
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            cookies_dir = APP_DIR / "_internal" / "cookies" / "iCloud"
            cookies_dir.mkdir(parents=True, exist_ok=True)
            return cookies_dir
        
        cookies_dir = get_app_dir() / "_internal" / "cookies" / "iCloud"
        cookies_dir.mkdir(parents=True, exist_ok=True)
        return cookies_dir
    
    def _get_export_dir(self):
        """エクスポートディレクトリを取得"""
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            export_dir = APP_DIR / "_internal" / "Export" / "iCloud"
            export_dir.mkdir(parents=True, exist_ok=True)
            return export_dir
        
        export_dir = get_app_dir() / "_internal" / "Export" / "iCloud"
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir
    
    def _get_cookie_file(self):
        """クッキーファイルパスを取得"""
        safe_profile = "".join(c if c.isalnum() else "_" for c in self.profile)
        if not safe_profile:
            safe_profile = "default"
        return self.cookies_dir / f"{safe_profile}_cookies.json"
    
    def _parse_proxy(self):
        """プロキシ設定をパース"""
        if not self.proxy:
            return None
        
        proxy = self.proxy.strip()
        
        if proxy.count(":") >= 3:
            parts = proxy.split(":")
            host = parts[0]
            port = parts[1]
            user = parts[2]
            password = ":".join(parts[3:])
            
            return {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": password
            }
        elif ":" in proxy:
            return {"server": f"http://{proxy}"}
        
        return None
    
    def _find_chrome_path(self):
        """システムにインストールされているChromeのパスを探す"""
        import platform
        
        if platform.system() == "Windows":
            possible_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
        elif platform.system() == "Darwin":
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
        else:
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
            ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def load_cookies(self):
        """保存されたクッキーを読み込む"""
        cookie_file = self._get_cookie_file()
        if cookie_file.exists():
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                return cookies
            except:
                pass
        return None
    
    def save_cookies(self):
        """クッキーを保存"""
        try:
            cookies = self.context.cookies()
            cookie_file = self._get_cookie_file()
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2)
            print("Cookies saved")
        except Exception as e:
            print(f"Failed to save cookies: {e}")
    
    def start_browser(self):
        """ブラウザを起動"""
        from playwright.sync_api import sync_playwright
        
        self.playwright = sync_playwright().start()
        
        proxy_settings = self._parse_proxy()
        
        launch_options = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"]
        }
        
        # システムのChromeを探す
        chrome_path = self._find_chrome_path()
        if chrome_path:
            launch_options["executable_path"] = chrome_path
            print(f"Using system Chrome: {chrome_path}")
        
        if proxy_settings:
            launch_options["proxy"] = proxy_settings
            print(f"Using proxy: {proxy_settings['server']}")
        
        # ブラウザ起動（フォールバック付き）
        try:
            self.browser = self.playwright.chromium.launch(**launch_options)
        except Exception as e:
            print(f"Failed to launch with options, trying channel='chrome': {e}")
            launch_options.pop("executable_path", None)
            launch_options.pop("args", None)
            launch_options["channel"] = "chrome"
            self.browser = self.playwright.chromium.launch(**launch_options)
        
        context_options = {
            "viewport": {"width": 1280, "height": 1280},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        self.context = self.browser.new_context(**context_options)
        
        # クッキーを読み込み
        cookies = self.load_cookies()
        if cookies:
            try:
                self.context.add_cookies(cookies)
                print("Loaded saved cookies")
            except:
                pass
        
        self.page = self.context.new_page()
        
        # ブラウザが閉じられた時の検知
        self._browser_closed = False
        self.page.on("close", self._on_page_closed)
        self.browser.on("disconnected", self._on_browser_disconnected)
        
        print("Browser started")
    
    def _on_page_closed(self):
        """ページが閉じられた時のコールバック"""
        print("Browser window closed by user")
        self._browser_closed = True
        self._stop_requested = True
    
    def _on_browser_disconnected(self):
        """ブラウザが切断された時のコールバック"""
        print("Browser disconnected")
        self._browser_closed = True
        self._stop_requested = True
    
    def _check_browser_closed(self):
        """ブラウザが閉じられたかチェックし、閉じられていたら例外を発生"""
        if self._browser_closed or self._stop_requested:
            raise Exception("Browser closed or stop requested")
    
    def close_browser(self):
        """ブラウザを閉じる"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except:
            pass
    
    def is_logged_in(self):
        """ログイン状態を確認"""
        try:
            email_elem = self.page.query_selector(".email")
            if email_elem:
                return True
            
            dashboard = self.page.query_selector("[data-testid='app-container']")
            if dashboard:
                return True
                
            return False
        except:
            return False
    
    def login(self):
        """iCloudにログイン"""
        print("\x00STATUS:Opening Page", flush=True)
        
        try:
            # iCloudのトップページへ
            self.page.goto(self.BASE_URL, wait_until="networkidle", timeout=60000)
            time.sleep(3)
            
            # 既にログインしているか確認
            if self.is_logged_in():
                print("Already logged in")
                return True
            
            # サインインボタンをクリック
            print("\x00STATUS:Clicking Sign In", flush=True)
            sign_in_btn = self.page.query_selector(".sign-in-button")
            if sign_in_btn:
                sign_in_btn.click()
                print("Clicked sign-in button, waiting for iframe...")
                time.sleep(8)
            
            # メールアドレス入力欄を全フレームから探す
            print("\x00STATUS:Entering Email", flush=True)
            
            email_input = None
            target = None
            
            selectors = [
                "#account_name_text_field",
                "input#account_name_text_field",
                "[id='account_name_text_field']",
                "input[autocomplete='username webauthn']",
                "input.form-textbox-input"
            ]
            
            for attempt in range(15):
                frames = self.page.frames
                print(f"Attempt {attempt + 1}: Searching {len(frames)} frames...")
                
                for frame in frames:
                    frame_url = frame.url if frame.url else "no-url"
                    
                    for selector in selectors:
                        try:
                            elem = frame.query_selector(selector)
                            if elem and elem.is_visible():
                                email_input = elem
                                target = frame
                                print(f"Found email input in frame: {frame_url[:60]}")
                                break
                        except:
                            continue
                    
                    if email_input:
                        break
                
                if email_input:
                    break
                    
                time.sleep(2)
            
            if not email_input:
                print("Could not find email input field after all attempts")
                return False
            
            email_input.click()
            time.sleep(0.5)
            email_input.fill(self.loginid)
            print(f"Entered email: {self.loginid}")
            time.sleep(1)
            
            # 続けるボタンをクリック
            print("\x00STATUS:Clicking Continue", flush=True)
            continue_btn = target.query_selector("#sign-in")
            if continue_btn:
                continue_btn.click()
                time.sleep(3)
            
            # パスワード入力
            print("\x00STATUS:Entering Password", flush=True)
            password_input = target.wait_for_selector("#password_text_field", timeout=10000)
            password_input.click()
            time.sleep(0.3)
            password_input.fill(self.loginpass)
            print("Entered password")
            time.sleep(0.5)
            
            # 「サインインしたままにする」にチェック
            try:
                remember_me = target.query_selector("#remember-me-label")
                if remember_me:
                    remember_me.click()
                    time.sleep(0.3)
            except:
                pass
            
            # サインインボタンをクリック
            print("\x00STATUS:Clicking Sign In", flush=True)
            sign_in_submit = target.query_selector("#sign-in")
            if sign_in_submit:
                sign_in_submit.click()
            
            time.sleep(5)
            
            # 2ファクタ認証の確認と待機（最大5分）
            print("\x00STATUS:Checking 2FA", flush=True)
            
            for i in range(60):
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    print("Stop requested during 2FA wait")
                    return False
                
                if self.is_logged_in():
                    print("Login successful")
                    self.save_cookies()
                    return True
                
                # 2FA画面の確認
                is_2fa = False
                for frame in self.page.frames:
                    try:
                        verify_elem = frame.query_selector(".verify-device, .trusteddevice-container, [data-mode='trustedDevice']")
                        if verify_elem:
                            is_2fa = True
                            break
                    except:
                        continue
                
                if is_2fa:
                    if i == 0:
                        print("\x00STATUS:Waiting 2FA", flush=True)
                        print("2FA required - please enter code manually")
                
                # 「信頼する」ボタンをクリック
                for frame in self.page.frames:
                    try:
                        trust_btn = frame.query_selector("button.button-rounded-rectangle[type='submit']")
                        if trust_btn and trust_btn.is_visible():
                            text = trust_btn.inner_text()
                            if "信頼" in text or "Trust" in text:
                                print(f"Found trust button: {text}")
                                trust_btn.click()
                                print("Clicked trust button")
                                time.sleep(3)
                                break
                        
                        buttons = frame.query_selector_all("button.button-rounded-rectangle")
                        for btn in buttons:
                            try:
                                if btn.is_visible():
                                    text = btn.inner_text()
                                    if "信頼する" in text or "Trust This" in text:
                                        print(f"Found trust button by text: {text}")
                                        btn.click()
                                        print("Clicked trust button")
                                        time.sleep(3)
                                        break
                            except:
                                continue
                    except:
                        continue
                
                time.sleep(5)
            
            # 最終確認
            if self.is_logged_in():
                print("Login successful")
                self.save_cookies()
                return True
            else:
                print("Login failed")
                return False
                
        except Exception as e:
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_hme_emails_via_api(self):
        """APIを使ってHMEメールアドレス一覧を取得"""
        try:
            print("Fetching HME emails via API...")
            
            # ブラウザからクッキーを取得
            cookies = self.context.cookies()
            
            # クッキーを文字列形式に変換
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # dsidを取得（X-APPLE-WEBAUTH-USERから）
            dsid = None
            for cookie in cookies:
                if cookie['name'] == 'X-APPLE-WEBAUTH-USER':
                    value = cookie['value']
                    if 'd=' in value:
                        dsid = value.split('d=')[-1].strip('"')
                        break
            
            if not dsid:
                print("Could not find dsid in cookies")
                return None
            
            print(f"Found dsid: {dsid}")
            
            # クライアントIDを生成
            client_id = str(uuid.uuid4())
            
            # APIエンドポイント（複数試す）
            base_urls = [
                "https://p40-maildomainws.icloud.com",
                "https://p68-maildomainws.icloud.com",
                "https://p103-maildomainws.icloud.com",
            ]
            
            params = {
                "clientBuildNumber": "2602Build17",
                "clientMasteringNumber": "2602Build17", 
                "clientId": client_id,
                "dsid": dsid
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "text/plain",
                "Origin": "https://www.icloud.com",
                "Referer": "https://www.icloud.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": cookie_str
            }
            
            for base_url in base_urls:
                try:
                    url = f"{base_url}/v2/hme/list"
                    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                    full_url = f"{url}?{query_string}"
                    
                    print(f"Trying: {base_url}...")
                    
                    req = urllib.request.Request(full_url, headers=headers, method='GET')
                    
                    with urllib.request.urlopen(req, timeout=30) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode('utf-8'))
                            
                            if data.get("success"):
                                result = data.get("result", {})
                                hme_emails = result.get("hmeEmails", [])
                                
                                # hmeフィールドからメールアドレスを抽出
                                emails = []
                                for item in hme_emails:
                                    if item.get("isActive"):
                                        hme = item.get("hme")
                                        if hme:
                                            emails.append(hme)
                                
                                print(f"Found {len(emails)} active HME emails via API")
                                return emails
                            else:
                                print(f"API returned success=false")
                        else:
                            print(f"API returned status {response.status}")
                        
                except Exception as e:
                    print(f"Error with {base_url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            print(f"API error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_hme_emails_via_browser(self):
        """ブラウザ経由でHMEメールアドレス一覧を取得"""
        try:
            print("\x00STATUS:Navigating to HME", flush=True)
            
            # iCloud設定のHMEページへ移動
            self.page.goto("https://www.icloud.com/icloudplus/", wait_until="networkidle", timeout=60000)
            time.sleep(5)
            
            # Hide My Email セクションを探してクリック
            hme_link = self.page.query_selector("text=Hide My Email")
            if hme_link:
                hme_link.click()
                time.sleep(3)
            
            # メールアドレス一覧を取得
            print("\x00STATUS:Fetching Emails", flush=True)
            
            # メールアドレス要素を取得
            email_elements = self.page.query_selector_all("[data-testid='hme-address'], .hme-email-address")
            
            emails = []
            for elem in email_elements:
                try:
                    email_text = elem.inner_text().strip()
                    if "@" in email_text:
                        emails.append(email_text)
                except:
                    continue
            
            return emails
            
        except Exception as e:
            print(f"Browser fetch error: {e}")
            return []
    
    def export_emails(self, emails):
        """メールアドレスをtxtファイルにエクスポート"""
        if not emails:
            print("No emails to export")
            return False
        
        try:
            # ファイル名（プロファイル名_日時.txt）
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_profile = "".join(c if c.isalnum() else "_" for c in self.profile)
            filename = f"{safe_profile}_{timestamp}.txt"
            
            export_path = self.export_dir / filename
            
            with open(export_path, 'w', encoding='utf-8') as f:
                for email in emails:
                    f.write(email + "\n")
            
            print(f"Exported {len(emails)} emails to {export_path}")
            
            return True
            
        except Exception as e:
            print(f"Export error: {e}")
            return False
    
    def run(self):
        """メイン実行"""
        print("=" * 50)
        print("Site: iCloud Mode: Collect")
        print("=" * 50)
        
        print("\x00STATUS:Starting Task", flush=True)
        
        try:
            # ブラウザ起動
            self.start_browser()
            
            # ログイン
            if not self.login():
                return False, [], "Login failed"
            
            # HMEメールアドレスを取得（API優先）
            print("\x00STATUS:Collecting Emails", flush=True)
            
            # まずAPI経由で試行（高速）
            emails = self.get_hme_emails_via_api()
            
            if not emails:
                # APIが失敗した場合、ブラウザ経由で試行
                print("API failed, trying browser method...")
                emails = self.get_hme_emails_via_browser()
            
            if emails:
                print(f"Found {len(emails)} HME emails")
                
                # エクスポート
                if self.export_emails(emails):
                    return True, [], None
                else:
                    return False, [], "Export failed"
            else:
                print("No HME emails found")
                return False, [], "No emails found"
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return False, [], str(e)
            
        finally:
            self.close_browser()


if __name__ == "__main__":
    # テスト用
    task_data = {
        "Loginid": "test@icloud.com",
        "Loginpass": "password",
        "Profile": "test",
        "Proxy": "",
        "Headless": False
    }
    
    bot = IcloudCollect(task_data)
    success, emails, error = bot.run()
    print(f"Result: success={success}, emails={len(emails) if emails else 0}, error={error}")