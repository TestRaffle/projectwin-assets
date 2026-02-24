"""
iCloud Generate モード
- iCloudにログイン
- Hide My Email のアドレスを指定数生成
- 1つ生成するごとに15分待機（BAN防止）
- 生成したアドレスをtxtファイルに保存
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


class IcloudGenerate:
    """iCloud Hide My Email Generateクラス"""
    
    BASE_URL = "https://www.icloud.com"
    WAIT_MINUTES = 15  # 生成間の待機時間（分）
    
    def __init__(self, task_data, settings=None):
        self.task_data = task_data
        self.settings = settings or {}
        
        # タスクデータから情報取得
        self.loginid = task_data.get("Loginid", "")
        self.loginpass = task_data.get("Loginpass", "")
        self.profile = task_data.get("Profile", "default")
        self.proxy = task_data.get("Proxy", "")
        self.headless = task_data.get("Headless", False)
        
        # 生成する数（Sizeから取得、デフォルト1）
        size_str = task_data.get("Size", "1")
        try:
            self.generate_count = int(size_str)
        except:
            self.generate_count = 1
        
        # 最大750に制限
        if self.generate_count > 750:
            self.generate_count = 750
        
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
    
    def generate_email_via_api(self):
        """APIを使って新しいHMEメールアドレスを生成して確定"""
        try:
            # ブラウザからクッキーを取得
            cookies = self.context.cookies()
            
            # クッキーを文字列形式に変換
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # dsidを取得
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
            
            # クライアントIDを生成
            client_id = str(uuid.uuid4())
            
            # APIエンドポイント（複数試す）
            base_urls = [
                "https://p103-maildomainws.icloud.com",
                "https://p40-maildomainws.icloud.com",
                "https://p68-maildomainws.icloud.com",
            ]
            
            params = {
                "clientBuildNumber": "2604Build17",
                "clientMasteringNumber": "2604Build17",
                "clientId": client_id,
                "dsid": dsid
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.icloud.com",
                "Referer": "https://www.icloud.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": cookie_str
            }
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            
            # Step 1: Generate（一時的なアドレスを生成）
            generate_payload = json.dumps({"langCode": "ja-jp"}).encode('utf-8')
            generated_email = None
            
            for base_url in base_urls:
                try:
                    url = f"{base_url}/v1/hme/generate?{query_string}"
                    
                    req = urllib.request.Request(url, data=generate_payload, headers=headers, method='POST')
                    
                    with urllib.request.urlopen(req, timeout=30) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode('utf-8'))
                            
                            if data.get("success"):
                                result = data.get("result", {})
                                generated_email = result.get("hme")
                                
                                if generated_email:
                                    print(f"Generated (temp): {generated_email}")
                                    break
                        else:
                            print(f"Generate API returned status {response.status}")
                        
                except Exception as e:
                    print(f"Generate error with {base_url}: {e}")
                    continue
            
            if not generated_email:
                print("Failed to generate email")
                return None
            
            # Step 2: Reserve（アドレスを確定して保存）
            reserve_payload = json.dumps({
                "hme": generated_email,
                "label": "sub",
                "note": ""
            }).encode('utf-8')
            
            for base_url in base_urls:
                try:
                    url = f"{base_url}/v1/hme/reserve?{query_string}"
                    
                    req = urllib.request.Request(url, data=reserve_payload, headers=headers, method='POST')
                    
                    with urllib.request.urlopen(req, timeout=30) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode('utf-8'))
                            
                            if data.get("success"):
                                result = data.get("result", {})
                                hme_info = result.get("hme", {})
                                reserved_email = hme_info.get("hme")
                                
                                if reserved_email:
                                    print(f"Reserved (confirmed): {reserved_email}")
                                    return reserved_email
                        else:
                            print(f"Reserve API returned success=false")
                        
                except Exception as e:
                    print(f"Reserve error with {base_url}: {e}")
                    continue
            
            print("Failed to reserve email")
            return None
            
        except Exception as e:
            print(f"Generate API error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def export_emails(self, emails):
        """生成したメールアドレスをtxtファイルに保存"""
        if not emails:
            print("No emails to export")
            return False
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_profile = "".join(c if c.isalnum() else "_" for c in self.profile)
            filename = f"{safe_profile}_generated_{timestamp}.txt"
            
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
        print("Site: iCloud Mode: Generate")
        print(f"Target: Generate {self.generate_count} emails")
        print("=" * 50)
        
        print("\x00STATUS:Starting Task", flush=True)
        
        try:
            # ブラウザ起動
            self.start_browser()
            
            # ログイン
            if not self.login():
                return False, [], "Login failed"
            
            # メールアドレスを生成
            generated_emails = []
            
            for i in range(self.generate_count):
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    print("Stop requested")
                    break
                
                print(f"\x00STATUS:Generating {i+1}/{self.generate_count}", flush=True)
                print(f"Generating email {i+1}/{self.generate_count}...")
                
                email = self.generate_email_via_api()
                
                if email:
                    generated_emails.append(email)
                    print(f"Created: {email}")
                    
                    # 最後の1つでなければ15分待機
                    if i < self.generate_count - 1:
                        wait_seconds = self.WAIT_MINUTES * 60
                        print(f"Waiting {self.WAIT_MINUTES} minutes before next generation...")
                        
                        # 1秒ごとにチェックしながら待機
                        for sec in range(wait_seconds):
                            if self._stop_requested or self._browser_closed:
                                print("Stop requested during wait")
                                break
                            
                            # 残り時間を表示（1分ごと）
                            remaining = wait_seconds - sec
                            if remaining % 60 == 0:
                                mins = remaining // 60
                                print(f"\x00STATUS:Waiting {mins}min", flush=True)
                            
                            time.sleep(1)
                        
                        if self._stop_requested or self._browser_closed:
                            break
                else:
                    print(f"Failed to generate email {i+1}")
                    # 失敗しても続行するが、待機時間は入れる
                    if i < self.generate_count - 1:
                        print("Waiting 1 minute before retry...")
                        for sec in range(60):
                            if self._stop_requested or self._browser_closed:
                                break
                            time.sleep(1)
            
            # 最後にまとめてエクスポート
            if generated_emails:
                self.export_emails(generated_emails)
                print(f"Successfully generated {len(generated_emails)} emails")
                return True, [], None
            else:
                print("No emails generated")
                return False, [], "No emails generated"
                
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
        "Headless": False,
        "Size": "2"
    }
    
    bot = IcloudGenerate(task_data)
    success, results, error = bot.run()
    print(f"Result: success={success}, error={error}")