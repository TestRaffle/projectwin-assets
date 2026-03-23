"""
X(Twitter) ブラウザモード
- Playwright + Chrome を使用
- ログイン処理
- クッキー保存/読み込み
- OTP認証対応
- Cloudflare対応
- ログイン後はユーザーが自由に操作可能
"""

# === コンソールなし起動時（pythonw / ダブルクリック）の対策 ===
# stdout/stderrがNoneの場合、ダミーに置き換えてprint()エラーを防ぐ
import sys
import os
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

import json
import time
import random
import re
import imaplib
import email
import email.header
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class XBrowser:
    """X(Twitter) ブラウザクラス"""
    
    LOGIN_URL = "https://x.com/i/flow/login"
    HOME_URL = "https://x.com/home"
    
    def __init__(self, task_data, settings=None):
        self.task_data = task_data
        self.settings = settings or {}
        
        self.profile = task_data.get("Profile", "")
        self.site = task_data.get("Site", "")
        self.mode = task_data.get("Mode", "")
        self.proxy = task_data.get("Proxy", "")
        self.url = task_data.get("URL", "")
        self.headless = task_data.get("Headless", False)
        
        self.login_id = task_data.get("Loginid", "")
        self.login_pass = task_data.get("Loginpass", "")
        self.mail = task_data.get("Mail", "")
        
        self._settings_dir = self._get_settings_dir()
        self._cookies_dir = self._get_cookies_dir()
        
        self.imap_settings = self._load_imap_settings()
        
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        self._worker = None
        self._stop_requested = False
        self._browser_closed = False
        self._closing_intentionally = False
        
        # Cloudflare解決で取得した情報
        self._cf_user_agent = None
        self._cf_cookies = None
        self._cf_request_headers = None
        self._cf_response_headers = None
    
    def _load_imap_settings(self):
        settings_file = self._settings_dir / "fetch_settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                accounts = data.get("accounts", [])
                for acc in accounts:
                    if acc.get("selected"):
                        return acc
                if accounts:
                    return accounts[0]
            except Exception as e:
                print(f"Failed to load IMAP settings: {e}")
        return {}
    
    def _get_settings_dir(self):
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
            return Path(__file__).parent.parent.parent / "settings"
    
    def _get_cookies_dir(self):
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            cookies_dir = APP_DIR / "_internal" / "cookies" / "X"
            cookies_dir.mkdir(parents=True, exist_ok=True)
            return cookies_dir
        
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
            cookies_dir = base_dir / "_internal" / "cookies" / "X"
        else:
            cookies_dir = Path(__file__).parent.parent.parent / "cookies" / "X"
        
        cookies_dir.mkdir(parents=True, exist_ok=True)
        return cookies_dir
    
    def _get_cookie_path(self):
        # Loginidをそのままファイル名に使用
        return self._cookies_dir / f"{self.login_id}.json"
    
    def _get_proxy_for_yescaptcha(self):
        """YesCaptcha用のプロキシ形式に変換"""
        if not self.proxy:
            return None
        
        parts = self.proxy.split(":")
        if len(parts) >= 4:
            return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        elif len(parts) >= 2:
            return f"http://{parts[0]}:{parts[1]}"
        return None
    
    def random_sleep(self, min_sec=0.5, max_sec=1.5):
        if self._stop_requested or self._browser_closed:
            return
        time.sleep(random.uniform(min_sec, max_sec))
    
    def start_browser(self, headless=False, user_agent=None):
        """ブラウザを起動（Braveを使用）"""
        self.playwright = sync_playwright().start()
        
        # Braveブラウザのパスを探す
        brave_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        
        browser_path = None
        for path in brave_paths:
            if os.path.exists(path):
                browser_path = path
                print(f"[Browser] Using Brave: {path}")
                break
        
        # Braveが見つからない場合はChromeにフォールバック
        if not browser_path:
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            ]
            for path in chrome_paths:
                if os.path.exists(path):
                    browser_path = path
                    print(f"[Browser] Brave not found, using Chrome: {path}")
                    break
        
        proxy_config = None
        if self.proxy:
            proxy_parts = self.proxy.split(":")
            if len(proxy_parts) >= 2:
                proxy_config = {
                    "server": f"http://{proxy_parts[0]}:{proxy_parts[1]}"
                }
                if len(proxy_parts) >= 4:
                    proxy_config["username"] = proxy_parts[2]
                    proxy_config["password"] = proxy_parts[3]
                print(f"[Proxy] Using: {proxy_parts[0]}:{proxy_parts[1]}")
        
        launch_options = {
            "headless": headless,
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
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-breakpad",
                "--disable-component-extensions-with-background-pages",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-features=TranslateUI",
                "--disable-hang-monitor",
                "--disable-ipc-flooding-protection",
                "--disable-prompt-on-repost",
                "--disable-renderer-backgrounding",
                "--disable-sync",
                "--enable-features=NetworkService,NetworkServiceInProcess",
                "--force-color-profile=srgb",
                "--metrics-recording-only",
                "--no-first-run",
                "--password-store=basic",
                "--use-mock-keychain",
                "--export-tagged-pdf",
            ]
        }
        
        if browser_path:
            launch_options["executable_path"] = browser_path
        else:
            launch_options["channel"] = "chrome"
        
        if proxy_config:
            launch_options["proxy"] = proxy_config
        
        self.browser = self.playwright.chromium.launch(**launch_options)
        
        # ブラウザプロセスのPIDを保存（ストップ時に使用）
        self._browser_pid = None
        try:
            if hasattr(self.browser, '_impl_obj'):
                impl = self.browser._impl_obj
                if hasattr(impl, '_connection') and hasattr(impl._connection, '_transport'):
                    transport = impl._connection._transport
                    if hasattr(transport, '_proc') and transport._proc:
                        self._browser_pid = transport._proc.pid
                        print(f"[Browser PID: {self._browser_pid}]")
        except:
            pass
        
        context_options = {
            "viewport": {"width": 1280, "height": 1280},
            "screen": {"width": 1280, "height": 1280},
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
            "permissions": ["geolocation"],
            "java_script_enabled": True,
            "bypass_csp": True,
            "ignore_https_errors": True,
        }
        
        # CloudFlareから取得したUser-Agentがあれば使用、なければ固定値
        if user_agent:
            context_options["user_agent"] = user_agent
            print(f"[Browser] Using CF User-Agent: {user_agent[:60]}...")
        else:
            context_options["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        
        self.context = self.browser.new_context(**context_options)
        self.context.on("close", self._on_browser_closed)
        
        self.page = self.context.new_page()
        self.page.on("close", self._on_page_closed)
        
        # ===== Stealth対策: Playwright/自動化検出を回避 =====
        self.page.add_init_script("""
            // 1. navigator.webdriver を undefined に
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true
            });
            
            // 2. Playwright特有のプロパティを削除
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__PW_inspect;
            
            // 3. chrome.runtime を偽装（拡張機能があるように見せる）
            if (!window.chrome) {
                window.chrome = {};
            }
            if (!window.chrome.runtime) {
                window.chrome.runtime = {
                    id: 'mocked-extension-id',
                    connect: function() {},
                    sendMessage: function() {},
                    onMessage: { addListener: function() {} }
                };
            }
            
            // 4. Permissions API を偽装
            const originalQuery = window.navigator.permissions?.query;
            if (originalQuery) {
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            }
            
            // 5. plugins と mimeTypes を偽装（空でないように）
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const plugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                    ];
                    plugins.length = 3;
                    return plugins;
                },
                configurable: true
            });
            
            Object.defineProperty(navigator, 'mimeTypes', {
                get: () => {
                    const mimeTypes = [
                        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }
                    ];
                    mimeTypes.length = 2;
                    return mimeTypes;
                },
                configurable: true
            });
            
            // 6. languages を偽装
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ja-JP', 'ja', 'en-US', 'en'],
                configurable: true
            });
            
            // 7. hardwareConcurrency を一般的な値に
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8,
                configurable: true
            });
            
            // 8. deviceMemory を一般的な値に
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8,
                configurable: true
            });
            
            // 9. maxTouchPoints を設定
            Object.defineProperty(navigator, 'maxTouchPoints', {
                get: () => 0,
                configurable: true
            });
            
            // 10. outerWidth/outerHeight の修正
            Object.defineProperty(window, 'outerWidth', {
                get: () => window.innerWidth + 16,
                configurable: true
            });
            Object.defineProperty(window, 'outerHeight', {
                get: () => window.innerHeight + 88,
                configurable: true
            });
            
            // 11. screen の異常な小数点を修正
            const screenWidth = window.screen.width;
            const screenHeight = window.screen.height;
            Object.defineProperty(window.screen, 'width', {
                get: () => Math.round(screenWidth),
                configurable: true
            });
            Object.defineProperty(window.screen, 'height', {
                get: () => Math.round(screenHeight),
                configurable: true
            });
            Object.defineProperty(window.screen, 'availWidth', {
                get: () => Math.round(screenWidth),
                configurable: true
            });
            Object.defineProperty(window.screen, 'availHeight', {
                get: () => Math.round(screenHeight) - 40,
                configurable: true
            });
            
            // 12. Notification API を偽装
            if (window.Notification) {
                Object.defineProperty(Notification, 'permission', {
                    get: () => 'default',
                    configurable: true
                });
            }
            
            // 13. console.debug をオーバーライド
            const originalDebug = console.debug;
            console.debug = function(...args) {
                if (args[0]?.toString().includes('playwright')) return;
                return originalDebug.apply(console, args);
            };
        """)
    
    def _on_browser_closed(self, context):
        # 意図的なブラウザクローズ中は無視
        if self._closing_intentionally:
            return
        print("Browser closed by user")
        self._browser_closed = True
        self._stop_requested = True
    
    def _on_page_closed(self, page):
        # 意図的なブラウザクローズ中は無視
        if self._closing_intentionally:
            return
        print("Page closed")
        self._browser_closed = True
        self._stop_requested = True
    
    def close_browser(self, intentional=False):
        """ブラウザを閉じる。intentional=Trueの場合、stop_requestedフラグを立てない"""
        self._closing_intentionally = True
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except:
            pass
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._closing_intentionally = False
    
    def save_cookies(self):
        try:
            cookie_path = self._get_cookie_path()
            cookies = self.context.cookies()
            
            # クッキーの有効期限を1年後に延長
            import time
            one_year_later = time.time() + (365 * 24 * 60 * 60)
            
            for cookie in cookies:
                # expires が設定されているクッキーのみ延長
                if 'expires' in cookie and cookie['expires'] > 0:
                    cookie['expires'] = one_year_later
            
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2)
            print(f"Cookies saved (extended expiry): {cookie_path}")
            return True
        except Exception as e:
            print(f"Failed to save cookies: {e}")
            return False
    
    def load_cookies(self):
        try:
            cookie_path = self._get_cookie_path()
            if cookie_path.exists():
                with open(cookie_path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                self.context.add_cookies(cookies)
                print(f"Cookies loaded: {cookie_path}")
                return True
        except Exception as e:
            print(f"Failed to load cookies: {e}")
        return False
    
    def human_type(self, selector, text, delay_min=50, delay_max=150):
        try:
            element = self.page.wait_for_selector(selector, timeout=10000)
            if element:
                element.click()
                self.random_sleep(0.2, 0.4)
                for char in text:
                    if self._stop_requested or self._browser_closed:
                        return False
                    element.type(char, delay=random.randint(delay_min, delay_max))
                return True
        except Exception as e:
            print(f"Type error: {e}")
        return False
    
    def is_logged_in(self, timeout=30000):
        """ログイン状態を確認（最大timeout ms待機）"""
        try:
            selectors = [
                'button[aria-label="アカウントメニュー"]',
                'button[aria-label="Account menu"]',
                'button[data-testid="SideNav_AccountSwitcher_Button"]',
            ]
            
            # 最大timeout ms待機してAccount menuを探す
            start_time = time.time()
            timeout_sec = timeout / 1000
            
            while time.time() - start_time < timeout_sec:
                for selector in selectors:
                    try:
                        element = self.page.query_selector(selector)
                        if element:
                            print("Login confirmed: Account menu found")
                            return True
                    except:
                        continue
                
                # ログインボタンが表示されたらログインしていない
                try:
                    login_button = self.page.query_selector('a[data-testid="loginButton"]')
                    if login_button:
                        print("Login button found - not logged in")
                        return False
                except:
                    pass
                
                time.sleep(0.5)
            
            return False
        except:
            return False
    
    def _check_and_click_retry_button(self):
        """エラー画面の「やりなおす」ボタンをチェックしてクリック"""
        try:
            # 「問題が発生しました」のエラー画面を検出
            error_selectors = [
                'span:has-text("やりなおす")',
                'span:has-text("再読み込み")',
                'span:has-text("Retry")',
                'span:has-text("Try again")',
                'button:has-text("やりなおす")',
                'button:has-text("Retry")',
            ]
            
            for selector in error_selectors:
                try:
                    retry_button = self.page.locator(selector).first
                    if retry_button.is_visible(timeout=2000):
                        print("Error page detected, clicking retry button...")
                        retry_button.click()
                        print("Retry button clicked")
                        return True
                except:
                    continue
            
            return False
        except Exception as e:
            print(f"Retry button check error: {e}")
            return False
    
    def _check_cloudflare(self):
        """Cloudflare 5秒盾が表示されているか確認"""
        try:
            selectors = [
                'text="セキュリティ検証の実行"',
                'text="Verify you are human"',
                'text="Verifying you are human"',
                'text="私はロボットではありません"',
                'text="人間であることを確認"',
                'text="Just a moment"',
                'iframe[src*="turnstile"]',
                'iframe[src*="cloudflare"]',
                'iframe[src*="challenges.cloudflare.com"]',
                '.cf-turnstile',
            ]
            
            for selector in selectors:
                try:
                    element = self.page.locator(selector).first
                    if element.is_visible(timeout=1000):
                        return True
                except:
                    continue
            
            try:
                title = self.page.title()
                if "just a moment" in title.lower() or "cloudflare" in title.lower():
                    return True
            except:
                pass
            
            return False
        except:
            return False
    
    def _load_captcha_settings(self):
        settings_file = self._settings_dir / "captcha_settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                sites = data.get("sites", [])
                for site in sites:
                    if site.get("selected"):
                        return site
                return sites[0] if sites else {}
            except:
                pass
        return {}
    
    def _handle_cloudflare(self):
        """Cloudflare 5秒盾をCloudFlareTaskS3で解決、またはTurnstileで解決"""
        try:
            print("\x00STATUS:Solving Cloudflare", flush=True)
            
            website_url = self.page.url
            proxy = self._get_proxy_for_yescaptcha()
            
            if not proxy:
                print("Proxy is required for CloudFlare solving")
                return self._wait_for_manual_solve()
            
            # CloudFlareTaskS3 を試す（Turnstileよりこちらを優先）
            print(f"Using CloudFlareTaskS3 for: {website_url}")
            
            solution = self._solve_cloudflare_5s(website_url, proxy)
            
            if not solution:
                print("CloudFlareTaskS3 failed")
                return self._wait_for_manual_solve()
            
            # 解決成功 - 情報を保存
            self._cf_cookies = solution.get("cookies", {})
            self._cf_user_agent = solution.get("user_agent", "")
            self._cf_request_headers = solution.get("request_headers", {})
            self._cf_response_headers = solution.get("headers", {})
            
            # headersからset-cookieを探してcookiesを補完
            if not self._cf_cookies or not self._cf_cookies.get("cf_clearance"):
                # response headersからcookieを探す
                for key, value in self._cf_response_headers.items():
                    if key.lower() == "set-cookie":
                        print(f"Found Set-Cookie header: {value[:100]}...")
                        # cf_clearanceを抽出
                        if "cf_clearance=" in value:
                            import re
                            match = re.search(r'cf_clearance=([^;]+)', value)
                            if match:
                                self._cf_cookies["cf_clearance"] = match.group(1)
                                print(f"Extracted cf_clearance from header!")
            
            # デバッグ: 全てのcookiesを表示
            print(f"\n{'='*50}")
            print("CloudFlare Solution Details:")
            print(f"{'='*50}")
            print(f"User-Agent: {self._cf_user_agent[:80]}..." if self._cf_user_agent else "No User-Agent!")
            print(f"Cookies received: {self._cf_cookies}")
            print(f"Response headers keys: {list(self._cf_response_headers.keys())}")
            print(f"Request headers keys: {list(self._cf_request_headers.keys())}")
            print(f"{'='*50}\n")
            
            # cf_clearanceがなくても、cookiesがあれば続行
            if not self._cf_cookies and not self._cf_user_agent:
                print("No cookies or user_agent in response!")
                return self._wait_for_manual_solve()
            
            # ブラウザを閉じて、新しいUser-Agentで再起動
            print("Restarting browser with CF credentials...")
            current_url = self.page.url
            self.close_browser(intentional=True)
            
            # フラグをリセット
            self._browser_closed = False
            self._stop_requested = False
            
            self.random_sleep(1, 2)
            
            # 新しいUser-Agentでブラウザを起動
            self.start_browser(headless=self.headless, user_agent=self._cf_user_agent)
            
            # 全てのCookieを追加（x.comドメイン用）
            cookie_list = []
            for name, value in self._cf_cookies.items():
                cookie_list.append({
                    "name": name,
                    "value": value,
                    "domain": ".x.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True if name == "cf_clearance" else False
                })
            
            if cookie_list:
                self.context.add_cookies(cookie_list)
                print(f"Added {len(cookie_list)} cookies: {list(self._cf_cookies.keys())}")
            else:
                print("No cookies to add, continuing anyway...")
            
            # ページにアクセス
            print(f"Navigating to: {current_url}")
            self.page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            self.random_sleep(3, 5)
            
            # Cloudflareが消えたか確認
            if not self._check_cloudflare():
                print("Cloudflare bypassed successfully!")
                return True
            
            print("Cloudflare still present after restart, trying manual wait...")
            return self._wait_for_manual_solve()
            
        except Exception as e:
            print(f"Cloudflare handling error: {e}")
            import traceback
            traceback.print_exc()
            return self._wait_for_manual_solve()
    
    def _find_turnstile_sitekey(self):
        """ページからTurnstileのsitekeyを探す"""
        try:
            # iframe内のsitekeyを探す
            iframes = self.page.locator('iframe[src*="challenges.cloudflare.com"]')
            count = iframes.count()
            
            for i in range(count):
                try:
                    src = iframes.nth(i).get_attribute("src")
                    if src and "sitekey=" in src:
                        # URLからsitekeyを抽出
                        import re
                        match = re.search(r'sitekey=([^&]+)', src)
                        if match:
                            return match.group(1)
                except:
                    continue
            
            # div要素のdata-sitekey属性を探す
            turnstile_div = self.page.locator('.cf-turnstile[data-sitekey]')
            if turnstile_div.count() > 0:
                return turnstile_div.first.get_attribute("data-sitekey")
            
            # ページソースから探す
            try:
                content = self.page.content()
                import re
                # sitekey形式: 0x で始まる
                match = re.search(r'sitekey["\s:=]+["\']?(0x[a-zA-Z0-9]+)', content)
                if match:
                    return match.group(1)
            except:
                pass
            
            return None
        except Exception as e:
            print(f"Error finding Turnstile sitekey: {e}")
            return None
    
    def _solve_with_turnstile(self, sitekey, website_url):
        """TurnstileTaskProxylessでCaptchaを解決"""
        try:
            from urllib import request
            
            captcha_settings = self._load_captcha_settings()
            client_key = captcha_settings.get("token", "")
            
            if not client_key:
                print("YesCaptcha API key not configured")
                return False
            
            print(f"\n{'='*50}")
            print("TurnstileTaskProxyless")
            print(f"{'='*50}")
            print(f"URL: {website_url}")
            print(f"Sitekey: {sitekey}")
            print(f"{'='*50}\n")
            
            create_data = {
                "clientKey": client_key,
                "task": {
                    "type": "TurnstileTaskProxyless",
                    "websiteURL": website_url,
                    "websiteKey": sitekey
                }
            }
            
            print("Creating TurnstileTaskProxyless task...")
            req = request.Request(
                "https://api.yescaptcha.com/createTask",
                data=json.dumps(create_data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
            
            print(f"Response: {json.dumps(result, indent=2)}")
            
            if result.get("errorId") != 0:
                print(f"Task creation error: {result.get('errorDescription')}")
                return False
            
            task_id = result.get("taskId")
            print(f"Task ID: {task_id}")
            print("Waiting for Turnstile solution...")
            
            for i in range(40):
                if self._stop_requested:
                    return False
                
                time.sleep(3)
                
                get_result_data = {"clientKey": client_key, "taskId": task_id}
                req = request.Request(
                    "https://api.yescaptcha.com/getTaskResult",
                    data=json.dumps(get_result_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                with request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                status = result.get("status")
                
                if status == "ready":
                    print("\nTurnstile solved!")
                    solution = result.get("solution", {})
                    token = solution.get("token", "")
                    
                    if not token:
                        print("No token in response!")
                        return False
                    
                    print(f"Token: {token[:50]}...")
                    
                    # トークンをページに注入
                    success = self._inject_turnstile_token(token)
                    if success:
                        self.random_sleep(3, 5)
                        if not self._check_cloudflare():
                            print("Turnstile bypassed successfully!")
                            return True
                        else:
                            print("Cloudflare still present after token injection")
                    
                    return False
                    
                elif status == "processing":
                    print(f"Processing... ({(i+1)*3}s)")
                else:
                    error_id = result.get("errorId", 0)
                    if error_id != 0:
                        print(f"Task error: {result.get('errorDescription')}")
                        return False
            
            print("Timeout waiting for Turnstile solution")
            return False
            
        except Exception as e:
            print(f"Turnstile solving error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _inject_turnstile_token(self, token):
        """Turnstileトークンをページに注入"""
        try:
            print("Attempting to inject Turnstile token...")
            
            # 複数の方法を試す
            result = self.page.evaluate(f'''() => {{
                let injected = false;
                
                // 方法1: cf-turnstile-response input要素
                const inputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
                inputs.forEach(input => {{
                    input.value = "{token}";
                    injected = true;
                    console.log("Injected into cf-turnstile-response input");
                }});
                
                // 方法2: data-turnstile-response属性を持つ要素
                const turnstileInputs = document.querySelectorAll('[data-turnstile-response]');
                turnstileInputs.forEach(input => {{
                    input.setAttribute('data-turnstile-response', "{token}");
                    if (input.tagName === 'INPUT' || input.tagName === 'TEXTAREA') {{
                        input.value = "{token}";
                    }}
                    injected = true;
                }});
                
                // 方法3: 隠しinputにトークンを設定
                const hiddenInputs = document.querySelectorAll('input[type="hidden"]');
                hiddenInputs.forEach(input => {{
                    if (input.name && (input.name.includes('turnstile') || input.name.includes('cf-'))) {{
                        input.value = "{token}";
                        injected = true;
                    }}
                }});
                
                // 方法4: window.turnstile のコールバック
                if (window.turnstile && window.turnstile.getResponse) {{
                    try {{
                        // Override getResponse to return our token
                        window.turnstile.getResponse = () => "{token}";
                        injected = true;
                    }} catch(e) {{}}
                }}
                
                // 方法5: iframe内のturnstileを探す
                const iframes = document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]');
                iframes.forEach(iframe => {{
                    try {{
                        // iframeを非表示にしてバイパスされたように見せる
                        iframe.style.display = 'none';
                    }} catch(e) {{}}
                }});
                
                // 方法6: グローバルコールバックを探して呼び出す
                const callbacks = ['onTurnstileSuccess', 'turnstileCallback', '__cfCallback'];
                callbacks.forEach(cbName => {{
                    if (typeof window[cbName] === 'function') {{
                        try {{
                            window[cbName]("{token}");
                            injected = true;
                            console.log("Called callback: " + cbName);
                        }} catch(e) {{}}
                    }}
                }});
                
                return {{ injected: injected }};
            }}''')
            
            print(f"Injection result: {result}")
            
            # ページをリロードしてトークンが有効か確認
            self.random_sleep(1, 2)
            
            # フォームの送信ボタンを探してクリック
            submit_clicked = self.page.evaluate('''() => {
                // 送信ボタンを探す
                const submitSelectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:contains("Continue")',
                    'button:contains("Verify")',
                    'button:contains("確認")',
                    '#challenge-form button',
                    '.challenge-form button'
                ];
                
                for (let selector of submitSelectors) {
                    try {
                        const btn = document.querySelector(selector);
                        if (btn && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    } catch(e) {}
                }
                
                // formを直接submit
                const forms = document.querySelectorAll('form');
                for (let form of forms) {
                    try {
                        form.submit();
                        return true;
                    } catch(e) {}
                }
                
                return false;
            }''')
            
            print(f"Submit button clicked: {submit_clicked}")
            
            return True
        except Exception as e:
            print(f"Token injection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _solve_cloudflare_5s(self, website_url, proxy):
        """YesCaptcha CloudFlareTaskS3 で5秒盾を解決"""
        try:
            from urllib import request
            
            captcha_settings = self._load_captcha_settings()
            client_key = captcha_settings.get("token", "")
            
            if not client_key:
                print("YesCaptcha API key not configured")
                return None
            
            print(f"\n{'='*50}")
            print("CloudFlareTaskS3")
            print(f"{'='*50}")
            print(f"URL: {website_url}")
            print(f"Proxy: {proxy}")
            print(f"{'='*50}\n")
            
            create_data = {
                "clientKey": client_key,
                "task": {
                    "type": "CloudFlareTaskS3",
                    "websiteURL": website_url,
                    "proxy": proxy,
                    "waitLoad": True,
                    "requiredCookies": ["cf_clearance", "__cf_bm"]
                }
            }
            
            print("Creating CloudFlareTaskS3 task...")
            req = request.Request(
                "https://api.yescaptcha.com/createTask",
                data=json.dumps(create_data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
            
            print(f"Response: {json.dumps(result, indent=2)}")
            
            if result.get("errorId") != 0:
                print(f"Task creation error: {result.get('errorDescription')}")
                return None
            
            task_id = result.get("taskId")
            print(f"Task ID: {task_id}")
            print("Waiting for solution (30-90 seconds)...")
            
            for i in range(60):
                if self._stop_requested:
                    return None
                
                time.sleep(3)
                
                get_result_data = {"clientKey": client_key, "taskId": task_id}
                req = request.Request(
                    "https://api.yescaptcha.com/getTaskResult",
                    data=json.dumps(get_result_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                with request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                status = result.get("status")
                
                if status == "ready":
                    print("\nCloudFlare solved!")
                    solution = result.get("solution", {})
                    print(f"Solution keys: {list(solution.keys())}")
                    
                    # 詳細なデバッグ出力
                    if "cookies" in solution:
                        print(f"Cookies type: {type(solution['cookies'])}")
                        print(f"Cookies content: {solution['cookies']}")
                    if "user_agent" in solution:
                        print(f"User-Agent: {solution['user_agent'][:100]}...")
                    if "request_headers" in solution:
                        print(f"Request headers: {list(solution['request_headers'].keys())}")
                    
                    return solution
                    
                elif status == "processing":
                    print(f"Processing... ({(i+1)*3}s)")
                else:
                    error_id = result.get("errorId", 0)
                    error_code = result.get("errorCode", "")
                    error_desc = result.get("errorDescription", "")
                    if error_id != 0:
                        print(f"Task error: errorId={error_id}, code={error_code}, desc={error_desc}")
                        return None
            
            print("Timeout (180s)")
            return None
            
        except Exception as e:
            print(f"CloudFlare solving error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _wait_for_manual_solve(self):
        """手動解決を待機しつつ、チェックボックスの自動クリックを試みる"""
        print("\n" + "="*50)
        print("CLOUDFLARE CHALLENGE DETECTED")
        print("="*50)
        print("Attempting to auto-click checkbox...")
        print("If auto-click fails, please solve manually.")
        print("Waiting for up to 120 seconds...")
        print("="*50 + "\n")
        print("\x00STATUS:Solving CF Challenge", flush=True)
        
        checkbox_clicked = False
        
        for i in range(120):
            if self._stop_requested or self._browser_closed:
                return False
            
            # Cloudflareが消えたか確認
            if not self._check_cloudflare():
                print(f"\nCloudflare cleared after {i+1} seconds!")
                return True
            
            # チェックボックスを探してクリック（最初の30秒間、3秒ごとに試行）
            if i < 30 and i % 3 == 0 and not checkbox_clicked:
                try:
                    clicked = self._try_click_cf_checkbox()
                    if clicked:
                        checkbox_clicked = True
                        print("Checkbox clicked, waiting for verification...")
                except Exception as e:
                    print(f"Checkbox click attempt failed: {e}")
            
            if i % 10 == 0 and i > 0:
                print(f"Still waiting... ({i}s)")
            
            time.sleep(1)
        
        print("Timeout waiting for Cloudflare solve (120s)")
        return False
    
    def _try_click_cf_checkbox(self):
        """Cloudflareのチェックボックスをクリック"""
        try:
            # iframe内のチェックボックスを探す
            cf_iframe = self.page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
            
            # チェックボックスのセレクター
            checkbox_selectors = [
                'input[type="checkbox"]',
                '#cf-turnstile-checkbox',
                '.cb-lb input',
                'label.cb-lb',
                '#challenge-stage input',
            ]
            
            for selector in checkbox_selectors:
                try:
                    checkbox = cf_iframe.locator(selector).first
                    if checkbox.is_visible(timeout=1000):
                        checkbox.click()
                        print(f"Clicked CF checkbox: {selector}")
                        return True
                except:
                    continue
            
            # iframe外のチェックボックスも探す
            for selector in checkbox_selectors:
                try:
                    checkbox = self.page.locator(selector).first
                    if checkbox.is_visible(timeout=1000):
                        checkbox.click()
                        print(f"Clicked checkbox: {selector}")
                        return True
                except:
                    continue
            
            # Turnstile widgetを探してクリック
            try:
                turnstile = self.page.locator('.cf-turnstile').first
                if turnstile.is_visible(timeout=1000):
                    # Turnstile widgetの中央をクリック
                    box = turnstile.bounding_box()
                    if box:
                        x = box['x'] + box['width'] / 2
                        y = box['y'] + box['height'] / 2
                        self.page.mouse.click(x, y)
                        print("Clicked Turnstile widget center")
                        return True
            except:
                pass
            
            return False
            
        except Exception as e:
            print(f"CF checkbox click error: {e}")
            return False
    
    def do_login(self):
        """ログイン処理"""
        try:
            print("\x00STATUS:Logging In", flush=True)
            
            try:
                self.page.remove_listener("close", self._on_page_closed)
            except:
                pass
            
            print("Opening new tab for x.com...")
            new_page = self.context.new_page()
            
            print("Navigating to x.com in new tab...")
            new_page.goto("https://x.com/", wait_until="domcontentloaded", timeout=60000)
            # ページ読み込み完了後、最小限の待機
            self.random_sleep(1, 2)
            
            print("Closing first tab...")
            old_page = self.page
            self.page = new_page
            self.page.on("close", self._on_page_closed)
            
            try:
                old_page.close()
            except:
                pass
            
            print("Switched to x.com tab")
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            if self.is_logged_in():
                print("Already logged in")
                return True, None
            
            print("Clicking login button...")
            try:
                login_button = self.page.locator('a[data-testid="loginButton"]')
                if login_button.is_visible():
                    login_button.click()
                    print("Login button clicked")
                else:
                    self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"Login button error: {e}, navigating directly...")
                self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 最小待機（ページ遷移のため）
            self.random_sleep(1, 2)
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            # エラー画面「やりなおす」ボタンをチェック（最大5秒待機）
            retry_clicked = self._check_and_click_retry_button()
            if retry_clicked:
                self.random_sleep(1, 2)
            
            # ユーザー名入力（見つかり次第即実行、最大45秒待機）
            print("Waiting for username input...")
            try:
                username_input = self.page.wait_for_selector(
                    'input[autocomplete="username"]',
                    timeout=45000
                )
                
                if username_input:
                    print(f"Entering username: {self.login_id}")
                    username_input.click()
                    self.random_sleep(0.3, 0.5)
                    username_input.fill(self.login_id)
                    self.random_sleep(0.5, 1)
                    
                    print("Clicking next button...")
                    next_button = self.page.locator('button:has-text("次へ"), button:has-text("Next")').first
                    if next_button.is_visible():
                        next_button.click()
                    else:
                        self.page.keyboard.press("Enter")
                    
                    # 次の画面の読み込みを最小限待機
                    self.random_sleep(1, 2)
            except Exception as e:
                print(f"Username input error: {e}")
                return False, "Login Failed"
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            # パスワード入力（見つかり次第即実行、最大45秒待機）
            print("Waiting for password input...")
            try:
                password_input = self.page.wait_for_selector(
                    'input[name="password"]',
                    timeout=45000
                )
                
                if password_input:
                    print("Entering password...")
                    password_input.click()
                    self.random_sleep(0.3, 0.5)
                    password_input.fill(self.login_pass)
                    self.random_sleep(0.5, 1)
                    
                    print("Clicking login button...")
                    login_submit = self.page.locator('button[data-testid="LoginForm_Login_Button"]')
                    if login_submit.is_visible():
                        login_submit.click()
                    else:
                        self.page.keyboard.press("Enter")
                    
                    # ログイン処理の最小待機
                    self.random_sleep(2, 3)
            except Exception as e:
                print(f"Password input error: {e}")
                return False, "Login Failed"
            
            # OTP確認
            if self._check_otp_required():
                print("\x00STATUS:OTP Required", flush=True)
                print("OTP verification required...")
                otp_success = self._handle_otp_verification()
                if not otp_success:
                    return False, "OTP Failed"
                self.random_sleep(3, 5)
            
            # Cloudflare確認
            if self._check_cloudflare():
                print("\x00STATUS:Cloudflare Detected", flush=True)
                print("Cloudflare detected, solving...")
                cf_success = self._handle_cloudflare()
                if not cf_success:
                    print("Cloudflare solving failed")
                    return False, "Cloudflare Failed"
                
                # ブラウザ再起動後、ログインページに戻る
                print("Returning to login flow after Cloudflare bypass...")
                self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                self.random_sleep(3, 4)
                
                # 再度ログイン処理
                return self._complete_login_after_cf()
            
            # ログイン成功確認
            print("Checking login status...")
            for i in range(30):
                if self._stop_requested or self._browser_closed:
                    return False, "Stopped"
                
                if self.is_logged_in():
                    print("Login successful!")
                    self.save_cookies()
                    return True, None
                
                if self._check_cloudflare():
                    print("Cloudflare appeared, solving...")
                    cf_success = self._handle_cloudflare()
                    if cf_success:
                        return self._complete_login_after_cf()
                    return False, "Cloudflare Failed"
                
                time.sleep(1)
            
            print("Login failed - account menu not found")
            return False, "Login Failed"
            
        except Exception as e:
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return False, "Login Failed"
    
    def _complete_login_after_cf(self):
        """Cloudflareバイパス後のログイン完了処理"""
        try:
            print("Completing login after Cloudflare bypass...")
            
            # ユーザー名入力
            try:
                username_input = self.page.wait_for_selector(
                    'input[autocomplete="username"]',
                    timeout=10000
                )
                if username_input:
                    print(f"Entering username: {self.login_id}")
                    username_input.click()
                    self.random_sleep(0.3, 0.5)
                    username_input.fill(self.login_id)
                    self.random_sleep(0.5, 1)
                    
                    next_button = self.page.locator('button:has-text("次へ"), button:has-text("Next")').first
                    if next_button.is_visible():
                        next_button.click()
                    else:
                        self.page.keyboard.press("Enter")
                    self.random_sleep(2, 3)
            except:
                pass
            
            # パスワード入力
            try:
                password_input = self.page.wait_for_selector(
                    'input[name="password"]',
                    timeout=10000
                )
                if password_input:
                    print("Entering password...")
                    password_input.click()
                    self.random_sleep(0.3, 0.5)
                    password_input.fill(self.login_pass)
                    self.random_sleep(0.5, 1)
                    
                    login_submit = self.page.locator('button[data-testid="LoginForm_Login_Button"]')
                    if login_submit.is_visible():
                        login_submit.click()
                    else:
                        self.page.keyboard.press("Enter")
                    self.random_sleep(3, 5)
            except:
                pass
            
            # OTP確認
            if self._check_otp_required():
                print("OTP required after CF bypass...")
                if not self._handle_otp_verification():
                    return False, "OTP Failed"
                self.random_sleep(3, 5)
            
            # ログイン確認
            for i in range(30):
                if self._stop_requested or self._browser_closed:
                    return False, "Stopped"
                if self.is_logged_in():
                    print("Login successful!")
                    self.save_cookies()
                    return True, None
                time.sleep(1)
            
            return False, "Login Failed"
            
        except Exception as e:
            print(f"Post-CF login error: {e}")
            return False, "Login Failed"
    
    def _check_otp_required(self):
        try:
            selectors = [
                'h1:has-text("メールを確認する")',
                'h1:has-text("Check your email")',
                'span:has-text("メールを確認する")',
                'span:has-text("Check your email")',
            ]
            for selector in selectors:
                try:
                    element = self.page.locator(selector).first
                    if element.is_visible(timeout=2000):
                        return True
                except:
                    continue
            
            otp_input = self.page.locator('input[data-testid="ocfEnterTextTextInput"]')
            try:
                if otp_input.is_visible(timeout=2000):
                    return True
            except:
                pass
            return False
        except:
            return False
    
    def _handle_otp_verification(self):
        try:
            print("\x00STATUS:Fetching OTP", flush=True)
            otp_code = self.fetch_otp_from_email(max_wait=120)
            
            if not otp_code:
                print("Failed to get OTP from email")
                return False
            
            print("\x00STATUS:Found OTP", flush=True)
            print(f"Found OTP: {otp_code}")
            
            print("\x00STATUS:Entering OTP", flush=True)
            otp_input = self.page.locator('input[data-testid="ocfEnterTextTextInput"]')
            try:
                otp_input.click()
                self.random_sleep(0.3, 0.5)
                otp_input.fill(otp_code)
                self.random_sleep(0.5, 1)
            except Exception as e:
                print(f"OTP input error: {e}")
                return False
            
            print("Clicking next button...")
            next_button = self.page.locator('button[data-testid="ocfEnterTextNextButton"]')
            try:
                if next_button.is_visible(timeout=3000):
                    next_button.click()
                else:
                    self.page.keyboard.press("Enter")
            except:
                self.page.keyboard.press("Enter")
            
            self.random_sleep(3, 5)
            return True
            
        except Exception as e:
            print(f"OTP verification error: {e}")
            return False
    
    def fetch_otp_from_email(self, max_wait=120):
        if not self.imap_settings:
            print("IMAP settings not configured")
            return None
        
        imap_server = self.imap_settings.get("imap_server", "")
        imap_port = self.imap_settings.get("imap_port", 993)
        email_address = self.imap_settings.get("email", "")
        email_password = self.imap_settings.get("password", "")
        
        if not all([imap_server, email_address, email_password]):
            print("IMAP settings incomplete")
            return None
        
        target_email = self.mail.lower().strip() if self.mail else self.login_id.lower().strip()
        print(f"Fetching OTP for: {target_email}")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            # ストップ/ブラウザ閉じチェック
            if self._stop_requested or self._browser_closed:
                print("Stop requested during OTP fetch")
                return None
            
            try:
                mail = imaplib.IMAP4_SSL(imap_server, imap_port)
                mail.login(email_address, email_password)
                mail.select("INBOX")
                
                _, message_numbers = mail.search(None, '(UNSEEN FROM "x.com")')
                
                if not message_numbers[0]:
                    _, message_numbers = mail.search(None, '(UNSEEN FROM "twitter")')
                
                if message_numbers[0]:
                    msg_nums = message_numbers[0].split()
                    msg_nums_to_check = msg_nums[-10:][::-1]  # 最新10件をチェック
                    
                    for msg_num in msg_nums_to_check:
                        # ストップチェック
                        if self._stop_requested or self._browser_closed:
                            mail.logout()
                            return None
                        
                        try:
                            _, msg_data = mail.fetch(msg_num, "(BODY.PEEK[])")
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    
                                    # 宛先（To）をチェック - target_emailと一致するか確認
                                    to_header = msg.get("To", "")
                                    # デコード処理
                                    if to_header:
                                        decoded_to = ""
                                        for part, encoding in email.header.decode_header(to_header):
                                            if isinstance(part, bytes):
                                                decoded_to += part.decode(encoding or 'utf-8', errors='ignore')
                                            else:
                                                decoded_to += part
                                        to_header = decoded_to.lower()
                                    
                                    # 宛先がtarget_emailと一致しない場合はスキップ
                                    if target_email not in to_header:
                                        continue
                                    
                                    print(f"Found email for {target_email}")
                                    body = self._get_email_body(msg)
                                    otp_match = re.search(r'(?:^|\s)([a-z0-9]{8})(?:\s|$)', body, re.MULTILINE)
                                    if otp_match:
                                        otp = otp_match.group(1)
                                        mail.store(msg_num, '+FLAGS', '\\Seen')
                                        mail.logout()
                                        print(f"OTP found: {otp}")
                                        return otp
                        except Exception as e:
                            print(f"Error processing email: {e}")
                            continue
                
                mail.logout()
            except Exception as e:
                print(f"Email error: {e}")
            
            # ストップチェック
            if self._stop_requested or self._browser_closed:
                print("Stop requested during OTP fetch")
                return None
            
            print("Waiting for OTP email...")
            # 5秒待機を1秒ずつに分割してストップチェック
            for _ in range(5):
                if self._stop_requested or self._browser_closed:
                    print("Stop requested during OTP fetch")
                    return None
                time.sleep(1)
        
        print("OTP fetch timeout")
        return None
    
    def _get_email_body(self, msg):
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        body = part.get_payload(decode=True).decode(charset, errors='ignore')
                    except:
                        body = str(part.get_payload(decode=True))
                    break
                elif content_type == "text/html" and not body:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        body = part.get_payload(decode=True).decode(charset, errors='ignore')
                    except:
                        body = str(part.get_payload(decode=True))
        else:
            charset = msg.get_content_charset() or 'utf-8'
            try:
                body = msg.get_payload(decode=True).decode(charset, errors='ignore')
            except:
                body = str(msg.get_payload(decode=True))
        return body
    
    def check_login_with_cookies(self):
        try:
            if not self.load_cookies():
                return False
            
            print("Checking login with cookies...")
            
            try:
                self.page.remove_listener("close", self._on_page_closed)
            except:
                pass
            
            print("Opening new tab for x.com...")
            new_page = self.context.new_page()
            new_page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=60000)
            # ページ読み込み完了後、最小限の待機
            self.random_sleep(1, 2)
            
            print("Closing first tab...")
            old_page = self.page
            self.page = new_page
            self.page.on("close", self._on_page_closed)
            
            try:
                old_page.close()
            except:
                pass
            
            print("Switched to x.com tab")
            
            if self.is_logged_in():
                print("Login confirmed with cookies")
                return True
            
            return False
        except Exception as e:
            print(f"Cookie login check error: {e}")
            return False
    
    def run(self):
        try:
            print("=" * 50)
            print(f"Site: {self.site} Mode: {self.mode}")
            print("=" * 50)
            
            if self._stop_requested:
                return False, "Stopped"
            
            print("\x00STATUS:Starting Task", flush=True)
            try:
                self.start_browser(headless=self.headless)
            except Exception as e:
                print(f"Browser start failed: {e}")
                return False, "Failed Browser"
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            print("\x00STATUS:Checking Login", flush=True)
            if not self.check_login_with_cookies():
                success, error = self.do_login()
                if not success:
                    return False, error
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            print("Login completed successfully")
            
            # Browserモード: URLにアクセスしてユーザー操作を待機
            success, error = self.do_browse()
            if not success:
                return False, error
            
            return True, None
            
        except Exception as e:
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return False, "Failed Unknown"
        finally:
            self.close_browser()
    
    def do_browse(self):
        """Browserモード: URLにアクセスしてユーザー操作を待機"""
        try:
            # ログイン確認（ログインしていなければエラー）
            if not self.is_logged_in():
                print("Not logged in, cannot browse")
                return False, "Login Failed"
            
            # URLが指定されていればそこにアクセス、なければホームへ
            target_url = self.url if self.url else self.HOME_URL
            
            print(f"Navigating to: {target_url}")
            print("\x00STATUS:Opening Page", flush=True)
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            # ページ読み込み完了後、最小限の待機
            self.random_sleep(1, 2)
            
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            
            # ナビゲーション成功
            print("\x00STATUS:Browsing", flush=True)
            print("Navigation successful!")
            print("User can now freely operate the browser.")
            print("Press Stop button to finish.")
            
            # Cookieを保存
            self.save_cookies()
            
            # ユーザー操作待機（ストップボタンが押されるまで）
            self.wait_for_user()
            
            # ストップボタンが押された場合のみSuccess
            if self._stop_requested:
                # 最後にCookieを保存
                self.save_cookies()
                return True, None
            
            # ブラウザが閉じられた場合
            if self._browser_closed:
                return False, "Browser Closed"
            
            return False, "Stopped"
            
        except Exception as e:
            if self._stop_requested or self._browser_closed:
                return False, "Stopped"
            print(f"Browse error: {e}")
            import traceback
            traceback.print_exc()
            return False, "Browse Failed"
    
    def wait_for_user(self):
        """ユーザー操作を待機（ストップボタンが押されるまで）"""
        print("Waiting for user... (Stop button to finish)")
        
        while not self._stop_requested and not self._browser_closed:
            try:
                # 1秒ごとにチェック
                time.sleep(1)
                
                # ブラウザがまだ開いているか確認
                if self.page and not self.page.is_closed():
                    continue
                else:
                    print("Browser was closed by user")
                    break
            except Exception as e:
                print(f"Wait error: {e}")
                break
        
        print("User operation finished")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-data", required=True)
    args = parser.parse_args()
    
    try:
        with open(args.task_data, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
    except Exception as e:
        print(f"Failed to load task data: {e}")
        return
    
    bot = XBrowser(task_data)
    success, error_status = bot.run()
    
    if error_status:
        print(f"ERROR:{error_status}")
    
    print(f"Bot finished with success={success}")


if __name__ == "__main__":
    main()