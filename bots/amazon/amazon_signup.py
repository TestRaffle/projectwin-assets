"""
Amazon 新規登録ボット
- メールアドレスでアカウント作成
- OTPコードはメールから自動取得
- 電話番号認証はSMS-Activate APIを使用
"""

import argparse
import json
import os
import sys
import time
import re
import random
import imaplib
import email
from email.header import decode_header
from pathlib import Path
from urllib import request, parse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class AmazonSignup:
    """Amazon新規登録クラス"""
    
    # サインインページURL（別ソフトウェアと同じ /ap/cnep 形式）
    SIGNIN_URL = "https://www.amazon.co.jp/ap/cnep?openid.return_to=https%3A%2F%2Fwww.amazon.co.jp%2Fyour-account&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=jpflex&openid.mode=checkid_setup&openid.ns.pape=http%3A%2F%2Fspecs.openid.net%2Fextensions%2Fpape%2F1.0&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
    
    # 登録ページURL（フォールバック用）
    REGISTER_URL = "https://www.amazon.co.jp/ap/register?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.co.jp%2F%3F_encoding%3DUTF8%26language%3Dja_JP%26ref_%3Dnav_custrec_newcust&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=jpflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
    
    # SMS API URLs
    HEROSMS_API = "https://hero-sms.com/stubs/handler_api.php"
    FIVESIM_API = "http://api1.5sim.net/stubs/handler_api.php"
    SMSMAN_API = "https://api.sms-man.com/stubs/handler_api.php"  # SMS-Man互換API
    SMSMAN_CONTROL_API = "https://api.sms-man.com/control/"  # SMS-Man独自API
    AMAZON_SERVICE_CODE = "am"  # AmazonのサービスコードID (HeroSMS/5sim用)
    AMAZON_APPLICATION_ID = "176"  # AmazonのアプリケーションID (SMS-Man独自API用)
    
    # HeroSMS国コード → 電話番号プレフィックス・Amazon国コードのマッピング
    # (phone_prefix, amazon_country_code)
    COUNTRY_INFO_HEROSMS = {
        "0": ("+7", "RU"),       # Russia
        "1": ("+380", "UA"),     # Ukraine
        "2": ("+7", "KZ"),       # Kazakhstan
        "3": ("+86", "CN"),      # China
        "4": ("+63", "PH"),      # Philippines
        "6": ("+62", "ID"),      # Indonesia
        "7": ("+60", "MY"),      # Malaysia
        "10": ("+84", "VN"),     # Vietnam
        "12": ("+1", "US"),      # USA
        "16": ("+44", "GB"),     # UK
        "22": ("+91", "IN"),     # India
        "33": ("+57", "CO"),     # Colombia
        "36": ("+1", "CA"),      # Canada
        "43": ("+49", "DE"),     # Germany
        "52": ("+66", "TH"),     # Thailand
        "54": ("+52", "MX"),     # Mexico
        "73": ("+55", "BR"),     # Brazil
        "78": ("+33", "FR"),     # France
        "86": ("+39", "IT"),     # Italy
        "175": ("+61", "AU"),    # Australia
        "182": ("+81", "JP"),    # Japan
        "190": ("+82", "KR"),    # South Korea
        "196": ("+65", "SG"),    # Singapore
    }
    
    # 5sim国名 → 電話番号プレフィックス・Amazon国コードのマッピング
    COUNTRY_INFO_5SIM = {
        "russia": ("+7", "RU"),
        "ukraine": ("+380", "UA"),
        "kazakhstan": ("+7", "KZ"),
        "china": ("+86", "CN"),
        "philippines": ("+63", "PH"),
        "indonesia": ("+62", "ID"),
        "malaysia": ("+60", "MY"),
        "vietnam": ("+84", "VN"),
        "usa": ("+1", "US"),
        "england": ("+44", "GB"),
        "india": ("+91", "IN"),
        "colombia": ("+57", "CO"),
        "canada": ("+1", "CA"),
        "germany": ("+49", "DE"),
        "thailand": ("+66", "TH"),
        "mexico": ("+52", "MX"),
        "brazil": ("+55", "BR"),
        "france": ("+33", "FR"),
        "italy": ("+39", "IT"),
        "australia": ("+61", "AU"),
        "japan": ("+81", "JP"),
        "southkorea": ("+82", "KR"),
        "singapore": ("+65", "SG"),
        "netherlands": ("+31", "NL"),
        "spain": ("+34", "ES"),
        "poland": ("+48", "PL"),
        "sweden": ("+46", "SE"),
        "switzerland": ("+41", "CH"),
        "austria": ("+43", "AT"),
        "belgium": ("+32", "BE"),
        "czech": ("+420", "CZ"),
        "denmark": ("+45", "DK"),
        "finland": ("+358", "FI"),
        "greece": ("+30", "GR"),
        "hungary": ("+36", "HU"),
        "ireland": ("+353", "IE"),
        "israel": ("+972", "IL"),
        "newzealand": ("+64", "NZ"),
        "norway": ("+47", "NO"),
        "portugal": ("+351", "PT"),
        "romania": ("+40", "RO"),
        "taiwan": ("+886", "TW"),
        "turkey": ("+90", "TR"),
        "hongkong": ("+852", "HK"),
        "argentina": ("+54", "AR"),
        "chile": ("+56", "CL"),
        "peru": ("+51", "PE"),
        "uae": ("+971", "AE"),
        "saudiarabia": ("+966", "SA"),
        "egypt": ("+20", "EG"),
        "southafrica": ("+27", "ZA"),
        "kenya": ("+254", "KE"),
        "nigeria": ("+234", "NG"),
        "pakistan": ("+92", "PK"),
        "bangladesh": ("+880", "BD"),
        "srilanka": ("+94", "LK"),
        "nepal": ("+977", "NP"),
        "myanmar": ("+95", "MM"),
        "cambodia": ("+855", "KH"),
        "laos": ("+856", "LA"),
    }
    
    # SMS-Man国コード → 電話番号プレフィックス・Amazon国コードのマッピング（独自API用）
    COUNTRY_INFO_SMSMAN = {
        "151": ("+93", "AF"),     # Afghanistan
        "178": ("+355", "AL"),    # Albania
        "137": ("+213", "DZ"),    # Algeria
        "153": ("+244", "AO"),    # Angola
        "119": ("+54", "AR"),     # Argentina
        "183": ("+374", "AM"),    # Armenia
        "185": ("+61", "AU"),     # Australia
        "130": ("+43", "AT"),     # Austria
        "116": ("+994", "AZ"),    # Azerbaijan
        "186": ("+1", "BS"),      # Bahamas
        "187": ("+973", "BH"),    # Bahrain
        "17": ("+880", "BD"),     # Bangladesh
        "188": ("+1", "BB"),      # Barbados
        "159": ("+32", "BE"),     # Belgium
        "189": ("+501", "BZ"),    # Belize
        "190": ("+229", "BJ"),    # Benin
        "192": ("+975", "BT"),    # Bhutan
        "169": ("+591", "BO"),    # Bolivia
        "193": ("+387", "BA"),    # Bosnia and Herzegovina
        "194": ("+267", "BW"),    # Botswana
        "150": ("+55", "BR"),     # Brazil
        "160": ("+359", "BG"),    # Bulgaria
        "196": ("+226", "BF"),    # Burkina Faso
        "197": ("+257", "BI"),    # Burundi
        "198": ("+238", "CV"),    # Cabo Verde
        "19": ("+855", "KH"),     # Cambodia
        "121": ("+237", "CM"),    # Cameroon
        "13": ("+1", "CA"),       # Canada
        "200": ("+236", "CF"),    # Central African Republic
        "122": ("+235", "TD"),    # Chad
        "201": ("+56", "CL"),     # Chile
        "3": ("+86", "CN"),       # China
        "114": ("+57", "CO"),     # Colombia
        "203": ("+269", "KM"),    # Comoros
        "102": ("+242", "CG"),    # Congo
        "170": ("+506", "CR"),    # Costa Rica
        "125": ("+385", "HR"),    # Croatia
        "205": ("+53", "CU"),     # Cuba
        "154": ("+357", "CY"),    # Cyprus
        "141": ("+420", "CZ"),    # Czechia
        "109": ("+225", "CI"),    # Côte d'Ivoire
        "177": ("+243", "CD"),    # DR Congo
        "206": ("+45", "DK"),     # Denmark
        "209": ("+1", "DO"),      # Dominican Republic
        "210": ("+593", "EC"),    # Ecuador
        "105": ("+20", "EG"),     # Egypt
        "211": ("+503", "SV"),    # El Salvador
        "212": ("+240", "GQ"),    # Equatorial Guinea
        "115": ("+372", "EE"),    # Estonia
        "148": ("+251", "ET"),    # Ethiopia
        "214": ("+298", "FO"),    # Faroe Islands
        "216": ("+358", "FI"),    # Finland
        "155": ("+33", "FR"),     # France
        "217": ("+594", "GF"),    # French Guiana
        "219": ("+241", "GA"),    # Gabon
        "110": ("+220", "GM"),    # Gambia
        "220": ("+995", "GE"),    # Georgia
        "123": ("+49", "DE"),     # Germany
        "118": ("+233", "GH"),    # Ghana
        "222": ("+30", "GR"),     # Greece
        "224": ("+1", "GD"),      # Grenada
        "225": ("+590", "GP"),    # Guadeloupe
        "171": ("+502", "GT"),    # Guatemala
        "145": ("+224", "GN"),    # Guinea
        "227": ("+245", "GW"),    # Guinea-Bissau
        "228": ("+592", "GY"),    # Guyana
        "108": ("+509", "HT"),    # Haiti
        "165": ("+504", "HN"),    # Honduras
        "99": ("+852", "HK"),     # Hong Kong
        "161": ("+36", "HU"),     # Hungary
        "229": ("+354", "IS"),    # Iceland
        "14": ("+91", "IN"),      # India
        "7": ("+62", "ID"),       # Indonesia
        "136": ("+98", "IR"),     # Iran
        "127": ("+964", "IQ"),    # Iraq
        "106": ("+353", "IE"),    # Ireland
        "98": ("+972", "IL"),     # Israel
        "163": ("+39", "IT"),     # Italy
        "230": ("+1", "JM"),      # Jamaica
        "231": ("+81", "JP"),     # Japan
        "232": ("+962", "JO"),    # Jordan
        "2": ("+7", "KZ"),        # Kazakhstan
        "96": ("+254", "KE"),     # Kenya
        "234": ("+965", "KW"),    # Kuwait
        "97": ("+996", "KG"),     # Kyrgyzstan
        "107": ("+856", "LA"),    # Laos
        "129": ("+371", "LV"),    # Latvia
        "235": ("+961", "LB"),    # Lebanon
        "236": ("+266", "LS"),    # Lesotho
        "237": ("+231", "LR"),    # Liberia
        "297": ("+218", "LY"),    # Libya
        "124": ("+370", "LT"),    # Lithuania
        "239": ("+352", "LU"),    # Luxembourg
        "104": ("+853", "MO"),    # Macao
        "101": ("+261", "MG"),    # Madagascar
        "240": ("+265", "MW"),    # Malawi
        "6": ("+60", "MY"),       # Malaysia
        "241": ("+960", "MV"),    # Maldives
        "146": ("+223", "ML"),    # Mali
        "244": ("+596", "MQ"),    # Martinique
        "245": ("+222", "MR"),    # Mauritania
        "246": ("+230", "MU"),    # Mauritius
        "18": ("+52", "MX"),      # Mexico
        "162": ("+373", "MD"),    # Moldova
        "149": ("+976", "MN"),    # Mongolia
        "117": ("+212", "MA"),    # Morocco
        "157": ("+258", "MZ"),    # Mozambique
        "9": ("+95", "MM"),       # Myanmar
        "251": ("+264", "NA"),    # Namibia
        "158": ("+977", "NP"),    # Nepal
        "128": ("+31", "NL"),     # Netherlands
        "254": ("+687", "NC"),    # New Caledonia
        "144": ("+64", "NZ"),     # New Zealand
        "20": ("+505", "NI"),     # Nicaragua
        "255": ("+227", "NE"),    # Niger
        "103": ("+234", "NG"),    # Nigeria
        "298": ("+389", "MK"),    # North Macedonia
        "259": ("+47", "NO"),     # Norway
        "260": ("+968", "OM"),    # Oman
        "16": ("+92", "PK"),      # Pakistan
        "300": ("+970", "PS"),    # Palestine
        "316": ("+507", "PA"),    # Panama
        "156": ("+675", "PG"),    # Papua New Guinea
        "164": ("+595", "PY"),    # Paraguay
        "143": ("+51", "PE"),     # Peru
        "8": ("+63", "PH"),       # Philippines
        "12": ("+48", "PL"),      # Poland
        "263": ("+351", "PT"),    # Portugal
        "174": ("+1", "PR"),      # Puerto Rico
        "264": ("+974", "QA"),    # Qatar
        "321": ("+383", "XK"),    # Republic of Kosovo
        "320": ("+211", "SS"),    # Republic of South Sudan
        "11": ("+40", "RO"),      # Romania
        "265": ("+250", "RW"),    # Rwanda
        "319": ("+262", "RE"),    # Réunion
        "305": ("+1", "KN"),      # Saint Kitts and Nevis
        "306": ("+1", "LC"),      # Saint Lucia
        "309": ("+1", "VC"),      # Saint Vincent and the Grenadines
        "133": ("+966", "SA"),    # Saudi Arabia
        "139": ("+221", "SN"),    # Senegal
        "111": ("+381", "RS"),    # Serbia
        "317": ("+232", "SL"),    # Sierra Leone
        "270": ("+65", "SG"),     # Singapore
        "271": ("+421", "SK"),    # Slovakia
        "138": ("+386", "SI"),    # Slovenia
        "272": ("+677", "SB"),    # Solomon Islands
        "167": ("+252", "SO"),    # Somalia
        "113": ("+27", "ZA"),     # South Africa
        "135": ("+34", "ES"),     # Spain
        "142": ("+94", "LK"),     # Sri Lanka
        "175": ("+249", "SD"),    # Sudan
        "274": ("+597", "SR"),    # Suriname
        "315": ("+268", "SZ"),    # Swaziland
        "126": ("+46", "SE"),     # Sweden
        "276": ("+41", "CH"),     # Switzerland
        "134": ("+886", "TW"),    # Taiwan
        "277": ("+992", "TJ"),    # Tajikistan
        "313": ("+255", "TZ"),    # Tanzania
        "132": ("+66", "TH"),     # Thailand
        "168": ("+670", "TL"),    # Timor-Leste
        "176": ("+228", "TG"),    # Togo
        "280": ("+1", "TT"),      # Trinidad and Tobago
        "166": ("+216", "TN"),    # Tunisia
        "140": ("+90", "TR"),     # Turkey
        "281": ("+993", "TM"),    # Turkmenistan
        "282": ("+1", "TC"),      # Turks and Caicos Islands
        "172": ("+971", "AE"),    # UAE
        "152": ("+256", "UG"),    # Uganda
        "100": ("+44", "GB"),     # United Kingdom
        "284": ("+598", "UY"),    # Uruguay
        "5": ("+1", "US"),        # USA
        "120": ("+998", "UZ"),    # Uzbekistan
        "147": ("+58", "VE"),     # Venezuela
        "10": ("+84", "VN"),      # Vietnam
        "112": ("+967", "YE"),    # Yemen
        "15": ("+260", "ZM"),     # Zambia
        "173": ("+263", "ZW"),    # Zimbabwe
    }
    
    def __init__(self, task_data, settings=None):
        """
        初期化
        
        Args:
            task_data: Excelから読み込んだ全カラムのデータ（辞書）
            settings: GUIから渡される設定（辞書）
        """
        self.task_data = task_data
        self.settings = settings or {}
        
        # 基本情報
        self.profile = task_data.get("Profile", "")
        self.site = task_data.get("Site", "")
        self.mode = task_data.get("Mode", "")
        self.proxy = task_data.get("Proxy", "")
        self.headless = task_data.get("Headless", False)
        
        # ログイン情報
        self.login_id = task_data.get("Loginid", "")  # メールアドレス
        self.login_pass = task_data.get("Loginpass", "")  # パスワード
        
        # 名前
        self.last_name = task_data.get("LastName", "")
        self.first_name = task_data.get("FirstName", "")
        self.full_name = f"{self.last_name} {self.first_name}".strip()
        
        # 設定ディレクトリを取得（exe化対応）
        self._settings_dir = self._get_settings_dir()
        
        # IMAP設定（メールOTP取得用）- amazon_browserと同じ形式で読み込み
        self.imap_settings = self._load_imap_settings()
        
        # SMS設定
        self.sms_settings = self._load_sms_settings()
        
        # Captcha設定（YesCaptchaなど）
        self.captcha_settings = self._load_captcha_settings()
        
        # General設定（リトライ回数など）
        self.general_settings = self._load_general_settings()
        self.max_retries = self.general_settings.get("retry_count", 3)
        
        # SMS-Activate関連
        self.sms_activation_id = None
        self.sms_phone_number = None
        
        # ブラウザ関連
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        # ストップ制御（GUIから設定される）
        self._worker = None  # GUIのワーカー参照
        self._stop_requested = False  # ストップフラグ
        self._browser_closed = False  # ブラウザ閉じ検知
        self._closing_intentionally = False  # 意図的クローズ中フラグ
    
    def _get_settings_dir(self):
        """設定ディレクトリを取得（exe化対応）"""
        # グローバル変数APP_DIRを確認（GUI.pyから渡される）
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            settings_dir = APP_DIR / "_internal" / "settings"
            if settings_dir.exists():
                return settings_dir
            # _internal/settingsがなければ直下のsettingsを試す
            settings_dir = APP_DIR / "settings"
            if settings_dir.exists():
                return settings_dir
        
        if getattr(sys, 'frozen', False):
            # exe化されている場合
            base_dir = Path(sys.executable).parent
            # _internal/settingsを優先
            settings_dir = base_dir / "_internal" / "settings"
            if settings_dir.exists():
                return settings_dir
            return base_dir / "settings"
        else:
            # 開発中
            return Path(__file__).parent.parent.parent / "settings"
    
    def _load_general_settings(self):
        """General設定を読み込む"""
        settings_file = self._settings_dir / "general_settings.json"
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load general settings: {e}")
        
        return {"retry_count": 3}
    
    def _load_imap_settings(self):
        """IMAP設定を読み込む（amazon_browserと同じ形式）"""
        settings_file = self._settings_dir / "fetch_settings.json"
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # accountsリストから選択されたアカウントを取得
                accounts = data.get("accounts", [])
                for acc in accounts:
                    if acc.get("selected"):
                        return acc
                # 選択されていなければ最初のアカウント
                if accounts:
                    return accounts[0]
                    
            except Exception as e:
                print(f"Failed to load IMAP settings: {e}")
        
        return {}
    
    def _load_sms_settings(self):
        """SMS設定を読み込む"""
        settings_file = self._settings_dir / "sms_settings.json"
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 選択されたサイトを返す
                sites = data.get("sites", [])
                for site in sites:
                    if site.get("selected"):
                        return site
                return sites[0] if sites else {}
            except Exception as e:
                print(f"Failed to load SMS settings: {e}")
        
        return {}
    
    def _load_captcha_settings(self):
        """Captcha設定を読み込む"""
        settings_file = self._settings_dir / "captcha_settings.json"
        
        print(f"[DEBUG] Loading captcha settings from: {settings_file}")
        print(f"[DEBUG] File exists: {settings_file.exists()}")
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"[DEBUG] Loaded data: {data}")
                # 選択されたサイトを返す
                sites = data.get("sites", [])
                for site in sites:
                    if site.get("selected"):
                        print(f"[DEBUG] Selected site: {site}")
                        return site
                result = sites[0] if sites else {}
                print(f"[DEBUG] No selected site, using first: {result}")
                return result
            except Exception as e:
                print(f"Failed to load Captcha settings: {e}")
        
        print("[DEBUG] No captcha settings file found")
        return {}
    
    def _parse_proxy(self):
        """プロキシ文字列をPlaywright形式に変換"""
        if not self.proxy:
            return None
        
        parts = self.proxy.split(":")
        
        if len(parts) == 2:
            return {"server": f"http://{parts[0]}:{parts[1]}"}
        elif len(parts) == 4:
            return {
                "server": f"http://{parts[0]}:{parts[1]}",
                "username": parts[2],
                "password": parts[3]
            }
        return None
    
    def _find_chrome_path(self):
        """システムにインストールされているChromeのパスを探す"""
        import platform
        
        if platform.system() == "Windows":
            # Windowsの一般的なChromeのパス
            possible_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
        elif platform.system() == "Darwin":
            # macOS
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
        else:
            # Linux
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
            ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def start_browser(self, headless=False):
        """ブラウザを起動"""
        self.playwright = sync_playwright().start()
        
        proxy_config = self._parse_proxy()
        
        # 起動オプション
        launch_options = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        }
        
        if proxy_config:
            launch_options["proxy"] = proxy_config
            print(f"Using proxy: {proxy_config['server']}")
        
        # システムのChromeを探す
        chrome_path = self._find_chrome_path()
        if chrome_path:
            launch_options["executable_path"] = chrome_path
            print(f"Using system Chrome: {chrome_path}")
        else:
            print("System Chrome not found, using Playwright's browser")
        
        try:
            self.browser = self.playwright.chromium.launch(**launch_options)
        except Exception as e:
            print(f"Failed to launch with options, trying channel='chrome': {e}")
            launch_options.pop("executable_path", None)
            launch_options["channel"] = "chrome"
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
        
        # コンテキストオプション
        context_options = {
            "viewport": {"width": 1280, "height": 1280},
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
            "ignore_https_errors": True,
        }
        
        self.context = self.browser.new_context(**context_options)
        
        # Amazonドメインへのリクエストのヘッダーを修正（別ソフトウェアと一致させる）
        def handle_route(route):
            headers = route.request.headers.copy()
            
            # cache-control: no-cache → max-age=0
            if headers.get("cache-control") == "no-cache":
                headers["cache-control"] = "max-age=0"
            
            # pragma: no-cache を削除
            if "pragma" in headers:
                del headers["pragma"]
            
            # ネットワーク品質を偽装（4G回線として）
            headers["ect"] = "4g"
            headers["rtt"] = "100"
            headers["downlink"] = "1.55"
            
            route.continue_(headers=headers)
        
        # Amazonドメインのみに適用（FunCaptchaには影響しない）
        self.context.route("**/*amazon.co.jp/**", handle_route)
        
        self.page = self.context.new_page()
        
        # WebAuthn API (Passkey) を無効化してPasskeyページを出さないようにする
        self.page.add_init_script("""
            // WebAuthn APIを無効化（Passkeyをサポートしていないように見せる）
            if (window.PublicKeyCredential) {
                // isUserVerifyingPlatformAuthenticatorAvailable を常にfalseを返すように
                window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
                // isConditionalMediationAvailable を常にfalseを返すように
                if (window.PublicKeyCredential.isConditionalMediationAvailable) {
                    window.PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
                }
            }
            // navigator.credentials を無効化
            if (navigator.credentials) {
                navigator.credentials.create = () => Promise.reject(new Error('NotSupportedError'));
                navigator.credentials.get = () => Promise.reject(new Error('NotSupportedError'));
            }
        """)
        
        # ブラウザが閉じられた時の検知
        self._browser_closed = False
        self.page.on("close", self._on_page_closed)
        self.context.on("close", self._on_context_closed)
        
        print("Browser started")
    
    def _on_page_closed(self, page=None):
        """ページが閉じられた時のコールバック"""
        # 意図的なブラウザクローズ中は無視
        if self._closing_intentionally:
            return
        print("Browser window closed by user")
        self._browser_closed = True
        self._stop_requested = True
    
    def _on_context_closed(self, context=None):
        """コンテキストが閉じられた時のコールバック"""
        # 意図的なブラウザクローズ中は無視
        if self._closing_intentionally:
            return
        print("Browser context closed")
        self._browser_closed = True
        self._stop_requested = True
    
    def close_browser(self, intentional=False):
        """ブラウザを閉じる。intentional=Trueの場合、イベントリスナーを無視"""
        if intentional:
            self._closing_intentionally = True
        try:
            if self.context:
                try:
                    self.context.close()
                except:
                    pass
            if self.browser:
                try:
                    self.browser.close()
                except:
                    pass
            if self.playwright:
                try:
                    self.playwright.stop()
                except:
                    pass
            print("Browser closed")
        except:
            pass
        finally:
            self._closing_intentionally = False
    
    # ========== クッキー管理 ==========
    
    def _get_cookies_dir(self):
        """クッキー保存ディレクトリを取得（exe化対応）"""
        # グローバル変数APP_DIRを確認（GUI.pyから渡される）
        global APP_DIR
        if 'APP_DIR' in globals() and APP_DIR:
            cookies_dir = APP_DIR / "_internal" / "cookies" / "Amazon"
            cookies_dir.mkdir(parents=True, exist_ok=True)
            return cookies_dir
        
        if getattr(sys, 'frozen', False):
            root_dir = Path(sys.executable).parent
        else:
            # Nuitka standalone対応
            exe_path = sys.executable.lower()
            if '.dist' in exe_path or 'projectwin' in exe_path:
                exe_dir = Path(sys.executable).parent
                for i in range(5):
                    check_dir = exe_dir
                    for _ in range(i):
                        check_dir = check_dir.parent
                    if (check_dir / "ProjectWIN.exe").exists():
                        root_dir = check_dir
                        break
                else:
                    root_dir = exe_dir
            else:
                root_dir = Path(__file__).resolve().parent.parent.parent
        
        cookies_dir = root_dir / "_internal" / "cookies" / "Amazon"
        cookies_dir.mkdir(parents=True, exist_ok=True)
        return cookies_dir
    
    def _get_cookie_file(self):
        """クッキーファイルパスを取得（Loginidベース）"""
        cookies_dir = self._get_cookies_dir()
        return cookies_dir / f"{self.login_id}.json"
    
    def save_cookies(self):
        """クッキーを保存（Amazon関連ドメインのみ）"""
        try:
            all_cookies = self.context.cookies()
            
            # Amazon関連ドメインのみフィルタリング（広告・トラッキング系を除外）
            allowed_domains = [".amazon.co.jp", "www.amazon.co.jp", "amazon.co.jp"]
            cookies = [
                c for c in all_cookies 
                if any(allowed in c.get("domain", "") for allowed in allowed_domains)
            ]
            
            # クッキーの有効期限を1年後に延長（整数に変換）
            import time
            one_year_later = int(time.time() + (365 * 24 * 60 * 60))
            
            for cookie in cookies:
                if 'expires' in cookie and cookie['expires'] > 0:
                    cookie['expires'] = one_year_later
            
            cookie_file = self._get_cookie_file()
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"Cookies saved: {cookie_file}")
            return True
        except Exception as e:
            print(f"Failed to save cookies: {e}")
            return False
    
    # ========== 電話番号削除 ==========
    
    def _check_and_handle_otp_verification(self):
        """OTP確認が求められている場合は処理する
        戻り値: "otp_handled" = OTP処理完了, True = OTP不要, False = 失敗
        """
        try:
            self.random_sleep(1, 2)
            
            # OTP入力フォームが表示されているか確認
            otp_input = self.page.query_selector("#cvf-input-code")
            if not otp_input:
                otp_input = self.page.query_selector("input[name='code']")
            if not otp_input:
                otp_input = self.page.query_selector("input[name='otpCode']")
            if not otp_input:
                otp_input = self.page.query_selector("input[autocomplete='one-time-code']")
            
            # ページ内容からOTP入力が必要か確認
            page_content = self.page.content()
            needs_otp = otp_input or "確認コード" in page_content or "verification code" in page_content.lower()
            
            if needs_otp and otp_input:
                print("\x00STATUS:Fetching OTP", flush=True)
                print("OTP verification required, fetching code from email (unread only)...")
                
                # メールからOTPを取得（未読メールのみ）
                otp_code = self.fetch_otp_from_email(max_wait=120)
                
                if otp_code:
                    print("\x00STATUS:Found OTP", flush=True)
                    print(f"Found OTP: {otp_code}")
                    print("\x00STATUS:Entering OTP", flush=True)
                    print(f"Entering OTP: {otp_code}")
                    
                    # OTP入力
                    try:
                        self.human_type("#cvf-input-code", otp_code)
                    except:
                        try:
                            otp_input.fill(otp_code)
                        except:
                            self.page.fill("input[name='code']", otp_code)
                    
                    self.random_sleep(1, 2)
                    
                    # コードを送信するボタンをクリック
                    print("\x00STATUS:Clicking Submit", flush=True)
                    print("Clicking submit button...")
                    submit_clicked = False
                    
                    # 様々なボタンセレクタを試す
                    submit_selectors = [
                        "#cvf-submit-otp-button",
                        "input[type='submit']",
                        "button[type='submit']",
                        ".a-button-input",
                        "#a-autoid-0-announce",
                        "span.a-button-inner input",
                        "button:has-text('確認')",
                        "button:has-text('送信')",
                        "input[value='確認']",
                    ]
                    
                    for selector in submit_selectors:
                        try:
                            # ナビゲーション待ちを避けるためno_wait_afterを使用
                            self.page.click(selector, timeout=3000, no_wait_after=True)
                            submit_clicked = True
                            break
                        except:
                            continue
                    
                    # ナビゲーション完了を別途待機（長めに）
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=120000)
                    except:
                        pass
                    
                    self.random_sleep(3, 5)
                    
                    return "otp_handled"  # OTP処理が行われたことを示す
                else:
                    print("Failed to get OTP from email")
                    return False
            
            # OTP入力が不要
            return True
            
        except Exception as e:
            print(f"OTP verification check error: {e}")
            return True  # エラーでも続行を試みる
    
    def _delete_phone_number(self):
        """登録した電話番号を削除（OTP処理済み前提）"""
        try:
            # 現在のURLを確認
            current_url = self.page.url
            
            # 既にアカウント管理ページにいない場合のみナビゲート
            if "account/manage" not in current_url:
                simple_manage_url = "https://www.amazon.co.jp/ax/account/manage"
                print("Navigating to account management page...")
                self.page.goto(simple_manage_url, wait_until="commit", timeout=120000)
                self.random_sleep(3, 5)
            
            # ページの読み込みを待つ
            print("Waiting for page to be ready...")
            self.page.wait_for_load_state("domcontentloaded", timeout=60000)
            
            # 編集ボタンを探す
            print("Looking for edit button...")
            edit_button = None
            
            # 最大3回試行
            for nav_attempt in range(3):
                try:
                    edit_button = self.page.wait_for_selector("#MOBILE_NUMBER_BUTTON", state="visible", timeout=30000)
                    if edit_button:
                        print("Edit button found")
                        break
                except:
                    pass
                
                # 見つからない場合、再ナビゲート
                if nav_attempt < 2:
                    print(f"Edit button not found, re-navigating (attempt {nav_attempt + 2}/3)...")
                    self.page.goto("https://www.amazon.co.jp/ax/account/manage", wait_until="commit", timeout=120000)
                    self.random_sleep(3, 5)
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                    except:
                        pass
            
            if not edit_button:
                print("Edit button not found after multiple attempts")
                return False
            
            # 編集ボタンをクリック（ナビゲーション待ちなし）
            print("Clicking edit button...")
            try:
                edit_button.scroll_into_view_if_needed()
                self.random_sleep(0.5, 1)
                edit_button.click(timeout=10000, no_wait_after=True)
            except:
                # JavaScriptでクリック
                print("Normal click failed, trying JavaScript click...")
                self.page.evaluate("document.querySelector('#MOBILE_NUMBER_BUTTON').click()")
            
            self.random_sleep(2, 3)
            
            # 削除リンクが表示されるまで待機してからクリック
            print("\x00STATUS:Clicking Delete", flush=True)
            print("Waiting for delete link...")
            
            # 削除リンクをクリックして確認ダイアログが出るまで最大5回試行
            confirm_appeared = False
            for click_attempt in range(5):
                try:
                    delete_link = self.page.wait_for_selector("#ap_delete_mobile_claim_link", state="visible", timeout=30000)
                    if delete_link:
                        print(f"Delete link found, clicking... (attempt {click_attempt + 1})")
                        
                        # スクロールして表示
                        delete_link.scroll_into_view_if_needed()
                        self.random_sleep(0.5, 1)
                        
                        # クリック方法を試す（no_wait_afterでナビゲーション待ちを回避）
                        try:
                            if click_attempt == 0:
                                delete_link.click(timeout=10000, no_wait_after=True)
                            elif click_attempt == 1:
                                self.page.evaluate("document.querySelector('#ap_delete_mobile_claim_link').click()")
                            elif click_attempt == 2:
                                self.page.locator("#ap_delete_mobile_claim_link").click(force=True, no_wait_after=True)
                            elif click_attempt == 3:
                                delete_link.dispatch_event("click")
                            else:
                                delete_link.click(force=True, no_wait_after=True)
                        except Exception as click_err:
                            print(f"Click method failed: {click_err}")
                        
                        self.random_sleep(1, 2)
                        
                        # 確認ボタンが表示されたかチェック
                        try:
                            confirm_check = self.page.wait_for_selector("#ap-remove-mobile-claim-submit-button", state="visible", timeout=10000)
                            if confirm_check:
                                print("Confirm dialog appeared!")
                                confirm_appeared = True
                                break
                        except:
                            print("Confirm dialog not appeared yet, retrying...")
                    else:
                        print("Delete link not found")
                except Exception as e:
                    print(f"Click attempt {click_attempt + 1} failed: {e}")
            
            if not confirm_appeared:
                print("Could not open confirm dialog after multiple attempts")
                return False
            
            # 「はい、削除します」ボタンが表示されるまで待機してからクリック
            print("\x00STATUS:Confirming Delete", flush=True)
            print("Waiting for confirm button...")
            try:
                confirm_button = self.page.wait_for_selector("#ap-remove-mobile-claim-submit-button", state="visible", timeout=60000)
                if confirm_button:
                    # 要素がクリック可能になるまで追加で待機
                    confirm_button.scroll_into_view_if_needed()
                    self.random_sleep(1, 2)
                    print("Confirm button found, clicking...")
                    
                    # 通常クリックを試みる（no_wait_afterでナビゲーション待ちを回避）
                    try:
                        confirm_button.click(timeout=10000, no_wait_after=True)
                    except:
                        # 失敗したらJavaScriptでクリック
                        print("Normal click failed, trying JavaScript click...")
                        self.page.evaluate("document.querySelector('#ap-remove-mobile-claim-submit-button').click()")
                    
                    self.random_sleep(3, 5)
                else:
                    print("Confirm button not found")
                    return False
            except Exception as e:
                print(f"Confirm button not found: {e}")
                return False
            
            # 成功メッセージを確認（最大30秒待機）
            print("Checking for success message...")
            for check_attempt in range(15):
                try:
                    # SUCCESS_MESSAGESを確認
                    success_elem = self.page.query_selector("#SUCCESS_MESSAGES")
                    if success_elem:
                        print("Phone number deletion confirmed!")
                        return True
                    
                    # ページ内容で確認
                    page_content = self.page.content()
                    if "削除されました" in page_content or "removed" in page_content.lower():
                        print("Phone number deletion confirmed (via page content)")
                        return True
                    
                    # MOBILE_NUMBER_BUTTONが「追加」になっていれば削除成功
                    try:
                        mobile_btn = self.page.query_selector("#MOBILE_NUMBER_BUTTON")
                        if mobile_btn:
                            btn_text = mobile_btn.inner_text()
                            if "追加" in btn_text or "Add" in btn_text:
                                print("Phone number deletion confirmed (button changed to Add)")
                                return True
                    except:
                        pass
                    
                except:
                    pass
                
                self.random_sleep(1, 2)
            
            print("Could not confirm phone number deletion")
            return False
            
        except Exception as e:
            print(f"Phone deletion error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # ========== 人間らしい入力 ==========
    
    def human_type(self, selector, text, min_delay=50, max_delay=150):
        """人間らしいタイピングでテキストを入力"""
        element = self.page.locator(selector)
        element.click()
        time.sleep(random.uniform(0.2, 0.5))
        
        for char in text:
            element.type(char, delay=random.randint(min_delay, max_delay))
            # たまにちょっと長めの間を入れる
            if random.random() < 0.1:
                time.sleep(random.uniform(0.1, 0.3))
        
        time.sleep(random.uniform(0.3, 0.6))
    
    def human_click(self, selector, timeout=30000):
        """人間らしいクリック（少し待ってからクリック）"""
        time.sleep(random.uniform(0.3, 0.8))
        self.page.click(selector, timeout=timeout)
        time.sleep(random.uniform(0.5, 1.0))
    
    def random_sleep(self, min_sec=1, max_sec=3):
        """ランダムな待機時間（ストップ対応）"""
        total_sleep = random.uniform(min_sec, max_sec)
        interval = 0.2
        elapsed = 0
        while elapsed < total_sleep:
            if self._stop_requested:
                return False
            time.sleep(min(interval, total_sleep - elapsed))
            elapsed += interval
        return True
    
    # ========== SMS API (HeroSMS / 5sim) ==========
    
    def _get_sms_api_url(self):
        """選択されたSMSサービスのAPIURLを取得"""
        site_id = self.sms_settings.get("site_id", "herosms")
        if site_id == "5sim":
            return self.FIVESIM_API
        elif site_id == "smsman":
            return self.SMSMAN_API
        return self.HEROSMS_API
    
    def sms_get_number(self):
        """SMSサービスから電話番号を取得（HeroSMS / 5sim / SMS-Man対応）"""
        token = self.sms_settings.get("token", "")
        country_code = self.sms_settings.get("country_code", "0")
        site_id = self.sms_settings.get("site_id", "herosms")
        
        if not token:
            print("SMS API token not configured")
            return None
        
        print(f"Using SMS service: {site_id}")
        print(f"Country code: {country_code}")
        
        # SMS-Manは独自APIを使用
        if site_id == "smsman":
            return self._smsman_get_number(token, country_code)
        
        # HeroSMS / 5sim は互換API
        params = {
            "api_key": token,
            "action": "getNumber",
            "service": self.AMAZON_SERVICE_CODE,
            "country": country_code
        }
        
        api_url = self._get_sms_api_url()
        
        try:
            url = f"{api_url}?{parse.urlencode(params)}"
            # APIキーをマスクしてログ出力
            masked_url = url.replace(token, token[:4] + "****" + token[-4:] if len(token) > 8 else "****")
            print(f"SMS API URL: {masked_url}")
            
            req = request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            with request.urlopen(req, timeout=30) as response:
                result = response.read().decode('utf-8')
                print(f"SMS API getNumber response: {result}")
                
                if result.startswith("ACCESS_NUMBER"):
                    # ACCESS_NUMBER:ID:NUMBER
                    parts = result.split(":")
                    self.sms_activation_id = parts[1]
                    self.sms_phone_number = parts[2]
                    print(f"Got phone number: {self.sms_phone_number} (ID: {self.sms_activation_id})")
                    return self.sms_phone_number
                elif result == "NO_NUMBERS":
                    print("No numbers available")
                elif result == "NO_BALANCE":
                    print("Insufficient SMS API balance")
                elif result == "BAD_KEY":
                    print("Invalid API key - please check your token in Settings > SMS")
                elif result == "BAD_SERVICE":
                    print("Invalid service code")
                else:
                    print(f"SMS API error: {result}")
                    
        except Exception as e:
            print(f"SMS API request failed: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def _smsman_get_number(self, token, country_code):
        """SMS-Man独自APIで電話番号を取得"""
        try:
            # SMS-Man独自API: get-number
            url = f"{self.SMSMAN_CONTROL_API}get-number?token={token}&country_id={country_code}&application_id={self.AMAZON_APPLICATION_ID}"
            
            # APIキーをマスクしてログ出力
            masked_url = url.replace(token, token[:4] + "****" + token[-4:] if len(token) > 8 else "****")
            print(f"SMS-Man API URL: {masked_url}")
            
            req = request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            with request.urlopen(req, timeout=30) as response:
                result = response.read().decode('utf-8')
                print(f"SMS-Man API response: {result}")
                
                # JSONレスポンスをパース
                import json
                data = json.loads(result)
                
                if "request_id" in data and "number" in data:
                    self.sms_activation_id = str(data["request_id"])
                    self.sms_phone_number = data["number"]
                    print(f"Got phone number: {self.sms_phone_number} (ID: {self.sms_activation_id})")
                    return self.sms_phone_number
                elif "error_code" in data:
                    error_code = data.get("error_code", "")
                    error_msg = data.get("error_msg", "")
                    print(f"SMS-Man API error: {error_code} - {error_msg}")
                    if error_code == "wrong_token":
                        print("Invalid API key - please check your token in Settings > SMS")
                    elif error_code == "no_numbers":
                        print("No numbers available for this country/service")
                    elif error_code == "no_balance":
                        print("Insufficient SMS API balance")
                else:
                    print(f"SMS-Man API unexpected response: {result}")
                    
        except Exception as e:
            print(f"SMS-Man API request failed: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def sms_get_code(self, max_wait=120):
        """SMSサービスからコードを取得（最大待機時間あり）"""
        if not self.sms_activation_id:
            print("No activation ID")
            return None
        
        token = self.sms_settings.get("token", "")
        site_id = self.sms_settings.get("site_id", "herosms")
        
        # SMS-Manは独自APIを使用
        if site_id == "smsman":
            return self._smsman_get_code(token, max_wait)
        
        # HeroSMS / 5sim は互換API
        params = {
            "api_key": token,
            "action": "getStatus",
            "id": self.sms_activation_id
        }
        
        api_url = self._get_sms_api_url()
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                url = f"{api_url}?{parse.urlencode(params)}"
                req = request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                with request.urlopen(req, timeout=30) as response:
                    result = response.read().decode('utf-8')
                    print(f"SMS API getStatus: {result}")
                    
                    if result.startswith("STATUS_OK"):
                        # STATUS_OK:CODE
                        code = result.split(":")[1]
                        print(f"Got SMS code: {code}")
                        return code
                    elif result == "STATUS_WAIT_CODE":
                        print("Waiting for SMS code...")
                        time.sleep(5)
                    elif result == "STATUS_CANCEL":
                        print("Activation cancelled")
                        return None
                    else:
                        print(f"SMS status: {result}")
                        time.sleep(5)
                        
            except Exception as e:
                print(f"SMS API status check failed: {e}")
                time.sleep(5)
        
        print("SMS code wait timeout")
        return None
    
    def _smsman_get_code(self, token, max_wait=120):
        """SMS-Man独自APIでSMSコードを取得"""
        import json
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                # SMS-Man独自API: get-sms
                url = f"{self.SMSMAN_CONTROL_API}get-sms?token={token}&request_id={self.sms_activation_id}"
                
                req = request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                with request.urlopen(req, timeout=30) as response:
                    result = response.read().decode('utf-8')
                    print(f"SMS-Man API get-sms: {result}")
                    
                    data = json.loads(result)
                    
                    if "sms_code" in data and data["sms_code"]:
                        code = data["sms_code"]
                        print(f"Got SMS code: {code}")
                        return code
                    elif "error_code" in data:
                        error_code = data.get("error_code", "")
                        if error_code == "wait_sms":
                            print("Waiting for SMS code...")
                        else:
                            print(f"SMS-Man error: {error_code}")
                    
            except json.JSONDecodeError:
                print("SMS-Man API response parse error")
            except Exception as e:
                print(f"SMS-Man API status check failed: {e}")
            
            time.sleep(5)
        
        print("SMS code wait timeout")
        return None
    
    def sms_set_status(self, status):
        """SMSサービスのステータスを更新"""
        if not self.sms_activation_id:
            return
        
        token = self.sms_settings.get("token", "")
        site_id = self.sms_settings.get("site_id", "herosms")
        
        # SMS-Manは独自APIを使用
        if site_id == "smsman":
            self._smsman_set_status(token, status)
            return
        
        # HeroSMS / 5sim は互換API
        # status: 1=SMS送信準備完了, 6=完了, 8=キャンセル
        params = {
            "api_key": token,
            "action": "setStatus",
            "id": self.sms_activation_id,
            "status": str(status)
        }
        
        api_url = self._get_sms_api_url()
        
        try:
            url = f"{api_url}?{parse.urlencode(params)}"
            req = request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            with request.urlopen(req, timeout=30) as response:
                result = response.read().decode('utf-8')
                print(f"SMS API setStatus({status}): {result}")
                
        except Exception as e:
            print(f"SMS API setStatus failed: {e}")
    
    def _smsman_set_status(self, token, status):
        """SMS-Man独自APIでステータスを更新"""
        try:
            # SMS-Man独自API: set-status
            # status mapping: 1=準備完了(不要), 6=完了(不要), 8=キャンセル(reject)
            if status == 8:  # キャンセル
                smsman_status = "reject"
            else:
                # SMS-Manでは準備完了や完了のステータス設定は不要
                print(f"SMS-Man: Status {status} auto-handled")
                return
            
            url = f"{self.SMSMAN_CONTROL_API}set-status?token={token}&request_id={self.sms_activation_id}&status={smsman_status}"
            
            req = request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            with request.urlopen(req, timeout=30) as response:
                result = response.read().decode('utf-8')
                print(f"SMS-Man API set-status: {result}")
                
        except Exception as e:
            print(f"SMS-Man API set-status failed: {e}")
    
    def get_country_info(self):
        """SMS設定から国情報を取得（サービスに応じたマッピングを使用）"""
        site_id = self.sms_settings.get("site_id", "herosms")
        country_code = self.sms_settings.get("country_code", "0")
        
        if site_id == "5sim":
            # 5simは国名（英語小文字）を使用
            info = self.COUNTRY_INFO_5SIM.get(country_code, ("+1", "US"))
        elif site_id == "smsman":
            # SMS-Manは数字の国コードを使用
            info = self.COUNTRY_INFO_SMSMAN.get(country_code, ("+1", "US"))
        else:
            # HeroSMSは数字の国コードを使用
            info = self.COUNTRY_INFO_HEROSMS.get(country_code, ("+1", "US"))
        
        return {
            "phone_prefix": info[0],
            "amazon_code": info[1],
            "sms_country_code": country_code
        }
    
    def get_phone_for_amazon(self):
        """Amazon用の電話番号フォーマットを取得（国番号なし）"""
        if not self.sms_phone_number:
            return None
        
        # 国番号を除去
        phone = self.sms_phone_number
        country_info = self.get_country_info()
        prefix = country_info["phone_prefix"]
        
        # +を除いた国番号で始まる場合は除去
        prefix_digits = prefix.replace("+", "")
        if phone.startswith(prefix_digits):
            phone = phone[len(prefix_digits):]
        
        print(f"Original phone: {self.sms_phone_number}")
        print(f"Country prefix: {prefix}")
        print(f"Phone without prefix: {phone}")
        
        return phone
    
    def select_country_dropdown(self):
        """Amazonの国選択ドロップダウンで正しい国を選択"""
        country_info = self.get_country_info()
        amazon_code = country_info["amazon_code"]
        phone_prefix = country_info["phone_prefix"]
        
        print(f"Selecting country: {amazon_code} ({phone_prefix})")
        
        try:
            # 国選択ドロップダウンを探す
            # Amazonの国選択は select タグまたは span/div のカスタムドロップダウン
            
            # まず select タグを試す
            select_elem = self.page.query_selector("select[name='countryCode']")
            if not select_elem:
                select_elem = self.page.query_selector("select.a-native-dropdown")
            if not select_elem:
                select_elem = self.page.query_selector("select[id*='country']")
            
            if select_elem:
                # selectタグの場合、valueで選択
                self.page.select_option("select", value=amazon_code)
                print(f"Selected country via select: {amazon_code}")
                self.random_sleep(0.5, 1)
                return True
            
            # カスタムドロップダウンの場合（span/divベース）
            # ドロップダウントリガーをクリック
            dropdown_trigger = self.page.query_selector(".a-dropdown-container")
            if not dropdown_trigger:
                dropdown_trigger = self.page.query_selector("[data-a-class='country-picker']")
            if not dropdown_trigger:
                dropdown_trigger = self.page.query_selector("span.a-dropdown-prompt")
            
            if dropdown_trigger:
                dropdown_trigger.click()
                self.random_sleep(0.5, 1)
                
                # 国コードに対応するオプションを探してクリック
                # 例: "CO +57" や "+57" を含む要素
                option_selectors = [
                    f"a[data-value='{amazon_code}']",
                    f"li[data-value='{amazon_code}']",
                    f"a:has-text('{amazon_code}')",
                    f"a:has-text('{phone_prefix}')",
                    f"li:has-text('{phone_prefix}')",
                ]
                
                for selector in option_selectors:
                    try:
                        option = self.page.query_selector(selector)
                        if option:
                            option.click()
                            print(f"Selected country via dropdown: {amazon_code}")
                            self.random_sleep(0.5, 1)
                            return True
                    except:
                        continue
            
            # 直接国コードを含むリンクを探す
            try:
                self.page.click(f"a:has-text('{phone_prefix}')")
                print(f"Selected country via link: {phone_prefix}")
                self.random_sleep(0.5, 1)
                return True
            except:
                pass
            
            print(f"Could not find country selector for {amazon_code}")
            return False
            
        except Exception as e:
            print(f"Country selection error: {e}")
            return False
    
    # ========== メールOTP取得（未読メールのみ対象） ==========
    
    def fetch_otp_from_email(self, max_wait=120):
        """
        メールからAmazonの確認コード（OTP）を取得
        ログインIDに対応する未読メールのみを対象とする（最新のものを優先）
        """
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
        
        target_email = self.login_id.lower().strip()
        print(f"Fetching OTP for: {target_email}")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                mail = imaplib.IMAP4_SSL(imap_server, imap_port)
                mail.login(email_address, email_password)
                mail.select("INBOX")
                
                # Amazonからの未読メールのみを検索
                _, message_numbers = mail.search(None, '(UNSEEN FROM "amazon")')
                
                if message_numbers[0]:
                    msg_nums = message_numbers[0].split()
                    
                    # 最新5件のみを逆順（新しい順）でチェック
                    msg_nums_to_check = msg_nums[-5:][::-1]
                    
                    for msg_num in msg_nums_to_check:
                        try:
                            # 本文を取得
                            _, msg_data = mail.fetch(msg_num, "(BODY.PEEK[])")
                            
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    
                                    # メールの宛先を確認
                                    to_addresses = []
                                    for header in ["To", "Delivered-To", "X-Original-To", "Envelope-To"]:
                                        val = msg.get(header, "")
                                        if val:
                                            to_addresses.append(val.lower())
                                    
                                    # 本文を取得
                                    body = self._get_email_body(msg)
                                    body_lower = body.lower()
                                    
                                    # 対象のログインIDがメールに関連しているか確認
                                    is_target = any(target_email in addr for addr in to_addresses) or target_email in body_lower
                                    
                                    if is_target:
                                        # OTPコードを抽出（6桁の数字）
                                        otp_match = re.search(r'\b(\d{6})\b', body)
                                        if otp_match:
                                            otp = otp_match.group(1)
                                            print(f"Found OTP: {otp}")
                                            
                                            # このメールを既読にする
                                            mail.store(msg_num, '+FLAGS', '\\Seen')
                                            mail.logout()
                                            return otp
                        except:
                            continue
                
                mail.logout()
                
            except Exception as e:
                print(f"Email error: {e}")
            
            print("Waiting for OTP...")
            time.sleep(5)
        
        print("OTP fetch timeout")
        return None
    
    def _get_email_body(self, msg):
        """メール本文を取得"""
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
    
    # ========== 登録処理 ==========
    
    def do_signup(self):
        """新規登録を実行
        
        Returns:
            tuple: (success: bool, error_status: str or None)
        """
        try:
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 1. サインインページにアクセス（Cookieを取得するため - 別ソフトウェアと同じフロー）
            print("\x00STATUS:Opening Page", flush=True)
            print("Step 1: Opening signin page...")
            
            # サインインページにアクセス（リトライあり）
            for attempt in range(self.max_retries + 1):
                # ★ ストップチェック
                if self._stop_requested:
                    print("Task stopped by user")
                    return False, "Stopped"
                try:
                    self.page.goto(self.SIGNIN_URL, wait_until="domcontentloaded", timeout=60000)
                    self.random_sleep(2, 3)
                    break
                except Exception as e:
                    if attempt < self.max_retries:
                        print(f"Retry {attempt + 1}/{self.max_retries}...")
                        time.sleep(3)
                    else:
                        print(f"Failed to access signin page after {self.max_retries} retries")
                        return False, "Failed Connection"
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # メールアドレス入力フォームが表示されるまで待機
            try:
                # サインインページのメール入力欄を待機
                self.page.wait_for_selector("#ap_email_login", state="visible", timeout=60000)
            except:
                print("Email input field not found")
                return False, "Failed Email Field"
            
            # 2. メールアドレスを入力（サインインページで直接入力）
            print("\x00STATUS:Entering Email", flush=True)
            print("Step 2: Entering email address...")
            self.human_type("#ap_email_login", self.login_id)
            self.random_sleep(0.5, 1)
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 3. 次に進むボタンをクリック
            print("\x00STATUS:Clicking Next", flush=True)
            print("Step 3: Clicking continue...")
            self.human_click("#continue")
            self.random_sleep(2, 3)
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 4. アカウントの作成に進むボタンをクリック
            print("\x00STATUS:Clicking Create", flush=True)
            print("Step 4: Clicking create account button...")
            try:
                self.page.wait_for_selector("#intention-submit-button", state="visible", timeout=60000)
                self.human_click("#intention-submit-button")
                self.random_sleep(2, 3)
            except:
                print("Create account button not found")
                return False, "Failed Create Btn"
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 5. 氏名を入力
            print("\x00STATUS:Entering Name", flush=True)
            print("Step 5: Entering name...")
            try:
                self.page.wait_for_selector("#ap_customer_name", state="visible", timeout=60000)
                self.human_type("#ap_customer_name", self.full_name)
                self.random_sleep(0.5, 1)
            except:
                print("Name field not found")
                return False, "Failed Name Field"
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 6. パスワードを入力
            print("\x00STATUS:Entering Password", flush=True)
            print("Step 6: Entering password...")
            self.human_type("#ap_password", self.login_pass)
            self.random_sleep(0.5, 1)
            
            # 7. パスワード確認を入力
            print("\x00STATUS:Confirming Password", flush=True)
            print("Step 7: Confirming password...")
            self.human_type("#ap_password_check", self.login_pass)
            self.random_sleep(1, 2)
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 8. メールアドレスを確認するボタンをクリック
            print("\x00STATUS:Clicking Email", flush=True)
            print("Step 8: Clicking verify email button...")
            self.human_click("#continue")
            self.random_sleep(2, 4)
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 9. キャプチャ処理（クイズを開始する）- 完了まで待つ
            print("\x00STATUS:Waiting CAPTCHA", flush=True)
            print("Step 9: Waiting for CAPTCHA to be solved...")
            if not self._wait_for_captcha_complete():
                print("CAPTCHA not solved or timeout")
                return False, "Failed Captcha"
            print("\x00STATUS:CAPTCHA Solved", flush=True)
            print("CAPTCHA solved or skipped")
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 10. メールOTPを取得して入力
            print("\x00STATUS:Fetching OTP", flush=True)
            print("Step 10: Waiting for email OTP...")
            otp_code = self.fetch_otp_from_email(max_wait=120)
            if otp_code:
                print("\x00STATUS:Found OTP", flush=True)
                print(f"Found OTP: {otp_code}")
                print("\x00STATUS:Entering OTP", flush=True)
                self.human_type("#cvf-input-code", otp_code)
                self.random_sleep(1, 2)
                
                # 確認ボタンをクリック
                try:
                    self.human_click("input[type='submit']")
                except:
                    try:
                        self.human_click("button[type='submit']")
                    except:
                        self.human_click(".a-button-input")
                self.random_sleep(2, 4)
            else:
                print("Failed to get OTP from email")
                return False, "Failed Email OTP"
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # 11. 電話番号登録
            print("\x00STATUS:Entering Phone", flush=True)
            print("Step 11: Phone number registration...")
            if not self._do_phone_verification():
                print("Phone verification failed")
                return False, "Failed Phone"
            
            # 12. SMS認証後のOTPページ対応
            print("Step 12: Checking post-SMS page...")
            self.random_sleep(2, 3)
            
            # ページ遷移の完了を待つ
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except:
                pass
            
            # OTPページにリダイレクトされた場合
            current_url = self.page.url
            if "transactionapproval" in current_url:
                print("Email OTP verification page detected, fetching OTP...")
                print("\x00STATUS:Fetching OTP", flush=True)
                
                # OTPコード入力欄を待機
                try:
                    self.page.wait_for_selector("#input-box-otp", state="visible", timeout=30000)
                except:
                    pass
                
                # メールからOTPを取得
                otp_code = self.fetch_otp_from_email(max_wait=120)
                if otp_code:
                    print(f"Found OTP: {otp_code}")
                    print("\x00STATUS:Entering OTP", flush=True)
                    
                    # OTPを入力
                    self.human_type("#input-box-otp", otp_code)
                    
                    # 「コードを送信する」ボタンをクリック（ナビゲーション待ちを避ける）
                    time.sleep(random.uniform(0.3, 0.8))
                    self.page.click("[aria-labelledby='cvf-submit-otp-button-announce']", timeout=10000, no_wait_after=True)
                    time.sleep(random.uniform(0.5, 1.0))
                    
                    # ナビゲーション完了を別途待機（長めに120秒）
                    print("Waiting for page navigation after OTP submit...")
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=120000)
                    except:
                        pass
                    
                    self.random_sleep(2, 3)
                else:
                    print("Failed to get OTP for account verification")
                    return False, "Failed Account OTP"
            
            # 13. 電話番号を削除（アカウント管理ページにいるはず）
            print("\x00STATUS:Clicking Edit", flush=True)
            print("Step 13: Deleting phone number...")
            if self._delete_phone_number():
                print("Phone number deleted successfully!")
                # 削除結果を目視確認できるよう待機
                self.random_sleep(3, 3)
            else:
                print("Failed to delete phone number, but account was created")
            
            # 14. クッキーを保存
            print("\x00STATUS:Saving Cookies", flush=True)
            print("Step 14: Saving cookies...")
            self.save_cookies()
            
            print("\x00STATUS:Account Created", flush=True)
            print("SUCCESS: Account created!")
            
            return True, None
            
        except Exception as e:
            print(f"Signup error: {e}")
            import traceback
            traceback.print_exc()
            return False, "Failed Unknown"
    
    def _wait_for_captcha_complete(self, max_wait=300):
        """キャプチャが完了するまで待機（自動解決または手動）"""
        print("Waiting for CAPTCHA...")
        start_time = time.time()
        
        self.random_sleep(3, 5)
        captcha_solved = False
        
        while time.time() - start_time < max_wait:
            # 停止チェック
            if self._stop_requested or self._browser_closed:
                print("Stop requested during CAPTCHA wait")
                return False
            
            try:
                # OTP入力フォームが出たらキャプチャ完了
                otp_input = self.page.query_selector("#cvf-input-code")
                if otp_input:
                    return True
                
                # 成功ページに進んだ場合
                page_content = self.page.content().lower()
                if "hello" in page_content or "さん" in page_content:
                    return True
                
                # 既に解決を試みた場合は待機のみ
                if captcha_solved:
                    time.sleep(2)
                    continue
                
                # クイズを開始するボタンを探してクリック
                clicked, captcha_frame = self._find_and_click_quiz_button()
                if clicked:
                    print("\x00STATUS:Quiz Clicked", flush=True)
                    # YesCaptchaで自動解決を試みる
                    if self.captcha_settings.get("token") and captcha_frame:
                        self.random_sleep(3, 5)
                        print("\x00STATUS:Sending CAPTCHA", flush=True)
                        
                        if self._solve_funcaptcha_with_yescaptcha(captcha_frame):
                            return True
                        else:
                            print("Auto-solve failed, waiting for manual...")
                            captcha_solved = True
                    else:
                        print("No API key, waiting for manual...")
                        captcha_solved = True
                
                time.sleep(3)
                
            except Exception as e:
                # ブラウザが閉じられた場合の例外をキャッチ
                if self._browser_closed or self._stop_requested:
                    print("Browser closed during CAPTCHA wait")
                    return False
                time.sleep(2)
        
        print("CAPTCHA timeout")
        return False
    
    def _find_and_click_quiz_button(self):
        """クイズを開始するボタンを探してクリック（iframe内優先）"""
        try:
            frames = self.page.frames
            
            for i, frame in enumerate(frames):
                try:
                    # 方法1: data-theme属性で検索
                    try:
                        btn = frame.query_selector("button[data-theme='home.verifyButton']")
                        if btn and btn.is_visible():
                            btn.click()
                            print("Quiz button clicked")
                            return True, frame
                    except:
                        pass
                    
                    # 方法2: aria-label属性で検索
                    try:
                        btn = frame.query_selector("button[aria-label='クイズを開始する']")
                        if btn and btn.is_visible():
                            btn.click()
                            print("Quiz button clicked")
                            return True, frame
                    except:
                        pass
                    
                    # 方法3: テキストで検索
                    try:
                        buttons = frame.query_selector_all("button")
                        for btn in buttons:
                            try:
                                text = btn.inner_text()
                                if "クイズを開始" in text:
                                    btn.click()
                                    print("Quiz button clicked")
                                    return True, frame
                            except:
                                continue
                    except:
                        pass
                    
                    # 方法4: JavaScriptでクリック
                    try:
                        result = frame.evaluate('''
                            () => {
                                let btn = document.querySelector("button[data-theme='home.verifyButton']");
                                if (btn) { btn.click(); return "data-theme"; }
                                
                                btn = document.querySelector("button[aria-label='クイズを開始する']");
                                if (btn) { btn.click(); return "aria-label"; }
                                
                                const buttons = document.querySelectorAll("button");
                                for (const b of buttons) {
                                    if (b.innerText && b.innerText.includes("クイズを開始")) {
                                        b.click();
                                        return "text";
                                    }
                                }
                                return null;
                            }
                        ''')
                        if result:
                            print("Quiz button clicked")
                            return True, frame
                    except:
                        pass
                        
                except:
                    continue
            
            # iframeで見つからなかった場合、メインページも確認
            try:
                result = self.page.evaluate('''
                    () => {
                        let btn = document.querySelector("button[data-theme='home.verifyButton']");
                        if (btn) { btn.click(); return "main-data-theme"; }
                        
                        btn = document.querySelector("button[aria-label='クイズを開始する']");
                        if (btn) { btn.click(); return "main-aria-label"; }
                        
                        const buttons = document.querySelectorAll("button");
                        for (const b of buttons) {
                            if (b.innerText && b.innerText.includes("クイズを開始")) {
                                b.click();
                                return "main-text";
                            }
                        }
                        return null;
                    }
                ''')
                if result:
                    print("Quiz button clicked")
                    return True, None
            except:
                pass
            
            return False, None
            
        except:
            return False, None
    
    def _solve_funcaptcha_with_yescaptcha(self, frame):
        """YesCaptcha APIを使ってFunCaptchaを解決（画像認識方式）"""
        # 画像認識方式を直接使用
        return self._solve_funcaptcha_with_classification(frame)
    
    def _get_funcaptcha_blob(self):
        """FunCaptchaのblobデータを取得"""
        try:
            # まずメインページで探す
            print("Searching for blob data...")
            
            # fc-tokenの値全体を取得してみる
            for f in self.page.frames:
                try:
                    token_info = f.evaluate('''
                        () => {
                            const input = document.querySelector("input[name='fc-token']");
                            if (input && input.value) {
                                return {
                                    found: true,
                                    value: input.value.substring(0, 200),
                                    hasBlob: input.value.includes("blob=")
                                };
                            }
                            
                            // id="fc-token"も探す
                            const input2 = document.querySelector("#fc-token, #FunCaptcha-Token");
                            if (input2 && input2.value) {
                                return {
                                    found: true,
                                    value: input2.value.substring(0, 200),
                                    hasBlob: input2.value.includes("blob=")
                                };
                            }
                            
                            return { found: false };
                        }
                    ''')
                    
                    if token_info and token_info.get('found'):
                        print(f"  fc-token found in frame, hasBlob: {token_info.get('hasBlob')}")
                        if token_info.get('hasBlob'):
                            # blobを抽出
                            blob = f.evaluate('''
                                () => {
                                    const inputs = document.querySelectorAll("input[name='fc-token'], #fc-token, #FunCaptcha-Token");
                                    for (const input of inputs) {
                                        if (input.value) {
                                            const match = input.value.match(/blob=([^|&]+)/);
                                            if (match) return match[1];
                                        }
                                    }
                                    return null;
                                }
                            ''')
                            if blob:
                                print(f"  Blob extracted: {blob[:50]}...")
                                return blob
                except Exception as e:
                    continue
            
            # メインページでも探す
            try:
                token_info = self.page.evaluate('''
                    () => {
                        const input = document.querySelector("input[name='fc-token'], #fc-token, #FunCaptcha-Token");
                        if (input && input.value) {
                            return {
                                found: true,
                                value: input.value.substring(0, 200),
                                hasBlob: input.value.includes("blob=")
                            };
                        }
                        return { found: false };
                    }
                ''')
                
                if token_info and token_info.get('found'):
                    print(f"  fc-token found in main page, hasBlob: {token_info.get('hasBlob')}")
            except:
                pass
            
            print("  No blob data found")
            return None
        except Exception as e:
            print(f"  Error getting blob: {e}")
            return None
    
    def _apply_funcaptcha_token(self, token, frame):
        """FunCaptchaトークンをページに適用"""
        try:
            print("Applying token to page...")
            
            # 方法1: fc-tokenのinputに設定して、コールバックを呼び出す
            applied = False
            
            # 全フレームでfc-tokenを探して設定
            for f in self.page.frames:
                try:
                    result = f.evaluate('''
                        (token) => {
                            let applied = false;
                            
                            // fc-token inputを探して設定
                            const inputs = document.querySelectorAll("input[name='fc-token'], #fc-token, #FunCaptcha-Token");
                            for (const input of inputs) {
                                input.value = token;
                                applied = true;
                                console.log("Token set to input");
                            }
                            
                            // ArkoseLabsのコールバックを探して呼び出す
                            if (typeof window.ArkoseEnforcement !== 'undefined') {
                                if (window.ArkoseEnforcement.setCompleted) {
                                    window.ArkoseEnforcement.setCompleted(token);
                                    console.log("ArkoseEnforcement.setCompleted called");
                                    applied = true;
                                }
                            }
                            
                            // 別のコールバック形式を探す
                            if (typeof window.fcCallback !== 'undefined') {
                                window.fcCallback(token);
                                console.log("fcCallback called");
                                applied = true;
                            }
                            
                            if (typeof window.captchaCallback !== 'undefined') {
                                window.captchaCallback(token);
                                console.log("captchaCallback called");
                                applied = true;
                            }
                            
                            return applied;
                        }
                    ''', token)
                    if result:
                        applied = True
                except:
                    continue
            
            # メインページでも試す
            try:
                self.page.evaluate('''
                    (token) => {
                        const inputs = document.querySelectorAll("input[name='fc-token'], #fc-token, #FunCaptcha-Token");
                        for (const input of inputs) {
                            input.value = token;
                        }
                    }
                ''', token)
            except:
                pass
            
            # 方法2: 少し待ってからCAPTCHA完了をチェック
            time.sleep(2)
            
            # 方法3: CAPTCHAのiframe内で検証完了を通知
            for f in self.page.frames:
                try:
                    f.evaluate('''
                        (token) => {
                            // parent windowにメッセージを送信
                            if (window.parent !== window) {
                                window.parent.postMessage({
                                    eventId: "challenge-complete",
                                    payload: { token: token }
                                }, "*");
                            }
                            
                            // グローバルなコールバックを探す
                            const callbacks = ['onComplete', 'onSuccess', 'onVerified', 'verificationComplete'];
                            for (const cb of callbacks) {
                                if (typeof window[cb] === 'function') {
                                    window[cb](token);
                                }
                            }
                        }
                    ''', token)
                except:
                    continue
            
            # 方法4: フォームのsubmitボタンをクリック（CAPTCHAが隠れた後）
            time.sleep(1)
            
            # CAPTCHAが完了したかチェック
            if self._check_captcha_complete():
                print("CAPTCHA completed after token apply")
                return True
            
            # 方法5: 検証ボタンを探してクリック
            try:
                verify_buttons = self.page.query_selector_all("button, input[type='submit']")
                for btn in verify_buttons:
                    try:
                        text = btn.inner_text() if hasattr(btn, 'inner_text') else ""
                        if any(word in text.lower() for word in ["verify", "検証", "続行", "continue", "submit", "送信"]):
                            btn.click()
                            print(f"Clicked verify button: {text}")
                            time.sleep(2)
                            break
                    except:
                        continue
            except:
                pass
            
            return applied
            
        except Exception as e:
            print(f"Error applying token: {e}")
            return False
    
    def _solve_funcaptcha_with_classification(self, frame):
        """フォールバック: 画像認識方式でFunCaptchaを解決"""
        client_key = self.captcha_settings.get("token", "")
        if not client_key:
            return False
        
        try:
            max_attempts = 5
            attempt = 0
            image_load_retries = 0
            max_image_load_retries = 10  # 画像読み込みの最大リトライ回数
            
            while attempt < max_attempts:
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return False
                
                # まず完了しているかチェック
                if self._check_captcha_complete():
                    print("CAPTCHA solved!")
                    return True
                
                # 1セット（1問または複数問）を解く
                result = self._solve_one_captcha_set(frame, client_key)
                
                if result == "solved":
                    print("CAPTCHA solved!")
                    return True
                elif result == "wrong":
                    # 間違えた場合のみattemptをカウント
                    attempt += 1
                    print(f"Wrong answer. Attempt {attempt}/{max_attempts}")
                    if attempt < max_attempts:
                        self._click_reload_button(frame)
                        time.sleep(2)
                elif result == "image_load_failed":
                    image_load_retries += 1
                    if image_load_retries >= max_image_load_retries:
                        print("Max image load retries reached")
                        return False
                    time.sleep(2)
                elif result == "api_error":
                    # APIエラーの場合はリロードして再試行（attemptカウントしない）
                    self._click_reload_button(frame)
                    time.sleep(3)
                else:
                    # その他のエラー
                    time.sleep(2)
            
            print("Max attempts reached")
            return False
            
        except Exception as e:
            print(f"Classification error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _solve_one_captcha_set(self, frame, client_key):
        """1セット（1問または複数問）のCAPTCHAを解く"""
        try:
            question_count = 0
            max_questions = 5  # 1セットの最大問題数
            is_first_question = True  # 最初の問題かどうか
            
            while question_count < max_questions:
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return "stopped"
                
                # 完了チェック
                if self._check_captcha_complete():
                    return "solved"
                
                # 1. 問題文を取得
                question = self._get_captcha_question(frame)
                if not question:
                    time.sleep(1)
                    if self._check_captcha_complete():
                        return "solved"
                    return "no_question"
                
                # エラーメッセージ（間違えた）の場合
                if "正しくない" in question or "incorrect" in question.lower():
                    return "wrong"
                
                # 問題数を解析（例: "2件中1件" → current=1, total=2）
                current_q, total_q = self._parse_question_count(question)
                if current_q == 1:
                    question_count = 0  # 新しいセットの開始
                    print(f"\x00STATUS:CAPTCHA Set ({total_q} questions)", flush=True)
                
                question_count += 1
                print(f"Question {current_q}/{total_q}: {question[:50]}...")
                
                # 2. 6枚の画像をキャプチャ（最初の問題以外も3秒待機）
                if not is_first_question:
                    time.sleep(3)
                is_first_question = False
                
                images = self._capture_all_captcha_states(frame)
                
                if not images or len(images) < 6:
                    print(f"Only got {len(images) if images else 0}/6 images")
                    return "image_load_failed"
                
                # 3. YesCaptcha APIに送信
                print("Sending to YesCaptcha...")
                create_task_data = {
                    "clientKey": client_key,
                    "task": {
                        "type": "FunCaptchaClassification",
                        "image": images,
                        "question": question
                    }
                }
                
                req = request.Request(
                    "https://api.yescaptcha.com/createTask",
                    data=json.dumps(create_task_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                with request.urlopen(req, timeout=60) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                if result.get("errorId") != 0:
                    error_desc = result.get('errorDescription', '')
                    print(f"API error: {error_desc}")
                    return "api_error"
                
                # 4. 結果を取得
                solution = result.get("solution", {})
                objects = solution.get("objects", [])
                
                if objects is None or (not objects and objects != [0]):
                    print("No valid answer from API")
                    return "api_error"
                
                target_index = objects[0]
                print(f"Answer: {target_index}")
                
                # 5. 回答して送信
                if self._click_arrow_times(frame, target_index):
                    time.sleep(0.5)
                    
                    self._click_submit_button(frame)
                    
                    # 送信後の状態を確認
                    for check in range(15):
                        time.sleep(1)
                        
                        # 完了チェック
                        if self._check_captcha_complete():
                            return "solved"
                        
                        # 次の問題または結果を確認
                        new_question = self._get_captcha_question(frame)
                        if new_question:
                            if "正しくない" in new_question:
                                return "wrong"
                            # 新しい問題が出た場合
                            if new_question != question:
                                print("Next question detected")
                                break
                
            return "max_questions"
            
        except Exception as e:
            print(f"Error solving captcha set: {e}")
            return "error"
    
    def _parse_question_count(self, question):
        """問題文から現在の問題番号と総数を解析"""
        import re
        # "X件中Y件" のパターンを探す
        match = re.search(r'(\d+)件中(\d+)件', question)
        if match:
            total = int(match.group(1))
            current = int(match.group(2))
            return current, total
        
        # "(X件中Y件)" のパターンも試す
        match = re.search(r'\((\d+)件中(\d+)件\)', question)
        if match:
            total = int(match.group(1))
            current = int(match.group(2))
            return current, total
        
        # 見つからない場合は1問のみと仮定
        return 1, 1
    
    def _capture_all_captcha_states(self, frame):
        """6つの状態の画像をキャプチャ（シンプル版 - 3秒待ってから開始）"""
        try:
            images = []
            
            # キャプチャコンテナ（矢印ボタンがあるフレーム）を探す
            captcha_frame = None
            for f in self.page.frames:
                try:
                    has_arrow = f.query_selector(".right-arrow, button[aria-label='次の画像を表示します']")
                    if has_arrow:
                        captcha_frame = f
                        break
                except:
                    continue
            
            if not captcha_frame:
                captcha_frame = frame
            
            # 3秒待機（画像が確実に読み込まれるまで）
            time.sleep(3)
            
            # 6枚の画像をキャプチャ
            for i in range(6):
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return images
                
                # 画像をキャプチャ
                image_data = self._capture_captcha_container(captcha_frame)
                if image_data:
                    images.append(image_data)
                    print(f"{i+1} ", end="", flush=True)
                else:
                    print(f"[{i+1}:failed] ", end="", flush=True)
                
                # 次の状態へ（最後以外は右矢印をクリック）
                if i < 5:
                    # 右矢印をクリック
                    captcha_frame.evaluate('''
                        () => {
                            const rightArrow = document.querySelector(".right-arrow, button[aria-label='次の画像を表示します'], a[aria-label='次の画像を表示します']");
                            if (rightArrow) {
                                rightArrow.click();
                                return true;
                            }
                            return false;
                        }
                    ''')
                    
                    # 画像が切り替わるのを待機
                    time.sleep(1)
            
            return images
            
        except Exception as e:
            print(f"Error: {e}")
            return []
    
    def _wait_for_new_captcha_image(self, frame, old_screenshot, max_wait=15):
        """新しいCAPTCHA画像が読み込まれるまで待機（前の画像と異なるまで待つ）"""
        try:
            start_time = time.time()
            new_screenshot = None
            stable_count = 0
            required_stable = 3  # 3回連続で同じなら安定とみなす
            
            while time.time() - start_time < max_wait:
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return False
                
                # 現在のスクリーンショットを取得
                current_screenshot = self._get_captcha_screenshot(frame)
                
                if current_screenshot and len(current_screenshot) > 1000:
                    # 前の画像と異なるかチェック
                    if old_screenshot is None or current_screenshot != old_screenshot:
                        # 新しい画像が安定しているかチェック
                        if new_screenshot == current_screenshot:
                            stable_count += 1
                            if stable_count >= required_stable:
                                print(f"New image loaded and stable after {time.time() - start_time:.1f}s")
                                return True
                        else:
                            stable_count = 0
                            new_screenshot = current_screenshot
                
                time.sleep(0.1)
            
            print(f"Timeout waiting for new image")
            return False
            
        except Exception as e:
            print(f"Error waiting for new image: {e}")
            return False
    
    def _wait_for_image_change(self, frame, prev_screenshot, max_wait=15):
        """画像が変化するのを待機（スクリーンショット比較）"""
        try:
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return prev_screenshot
                
                # 現在のスクリーンショットを取得
                current_screenshot = self._get_captcha_screenshot(frame)
                
                if current_screenshot:
                    # 初回（prev_screenshotがNone）
                    if prev_screenshot is None:
                        return current_screenshot
                    
                    # スクリーンショットが変わったかチェック（バイナリ比較）
                    if current_screenshot != prev_screenshot:
                        # 少し待って安定させる
                        time.sleep(0.1)
                        return current_screenshot
                
                time.sleep(0.05)  # 50msごとにチェック
            
            # タイムアウト時は現在のスクリーンショットを返す
            return self._get_captcha_screenshot(frame) or prev_screenshot
            
        except:
            return prev_screenshot
    
    def _get_captcha_screenshot(self, frame):
        """CAPTCHAのメイン画像部分のスクリーンショットを取得"""
        try:
            # 画像要素を探してスクリーンショット
            for f in self.page.frames:
                try:
                    # メイン画像（右側の大きい画像）を探す
                    img = f.query_selector("img[aria-label*='画像'], img.sc-7csxyx-1")
                    if img:
                        box = img.bounding_box()
                        if box and box['width'] > 100 and box['height'] > 100:
                            screenshot = img.screenshot()
                            if screenshot and len(screenshot) > 1000:  # 最低1KB以上
                                return screenshot
                except:
                    continue
            
            # 見つからない場合はanswer-frameを探す
            for f in self.page.frames:
                try:
                    container = f.query_selector(".answer-frame, .sc-7csxyx-0")
                    if container:
                        box = container.bounding_box()
                        if box and box['width'] > 100:
                            screenshot = container.screenshot()
                            if screenshot and len(screenshot) > 1000:
                                return screenshot
                except:
                    continue
            
            return None
        except:
            return None
    
    def _wait_for_captcha_image_loaded(self, frame, max_wait=15):
        """CAPTCHA画像の読み込み完了を待機（最大max_wait秒）"""
        try:
            start_time = time.time()
            last_src = None  # 前回の画像srcを記録
            
            while time.time() - start_time < max_wait:
                # 停止チェック
                if self._stop_requested or self._browser_closed:
                    return False
                
                # 全フレームで画像の読み込み状態をチェック
                for f in self.page.frames:
                    try:
                        result = f.evaluate('''
                            () => {
                                // 方法1: imgタグをチェック
                                const imgs = document.querySelectorAll("img");
                                for (const img of imgs) {
                                    // CAPTCHAの画像は通常100px以上
                                    if (img.complete && img.naturalWidth > 100 && img.naturalHeight > 100) {
                                        return { loaded: true, src: img.src.substring(0, 50) };
                                    }
                                }
                                
                                // 方法2: background-imageをチェック
                                const divs = document.querySelectorAll("div, span");
                                for (const div of divs) {
                                    const bg = window.getComputedStyle(div).backgroundImage;
                                    if (bg && bg !== "none" && bg.includes("url")) {
                                        const rect = div.getBoundingClientRect();
                                        if (rect.width > 100 && rect.height > 100) {
                                            return { loaded: true, src: "bg-image" };
                                        }
                                    }
                                }
                                
                                // 方法3: canvasをチェック
                                const canvases = document.querySelectorAll("canvas");
                                for (const canvas of canvases) {
                                    if (canvas.width > 100 && canvas.height > 100) {
                                        return { loaded: true, src: "canvas" };
                                    }
                                }
                                
                                return { loaded: false };
                            }
                        ''')
                        
                        if result and result.get('loaded'):
                            current_src = result.get('src', '')
                            # 画像が変わったか、初回検出の場合
                            if last_src is None or current_src != last_src:
                                return True
                    except:
                        continue
                
                time.sleep(0.05)  # 50msごとにチェック
            
            return False
            
        except:
            return False
    
    def _capture_captcha_container(self, frame):
        """左の数字画像＋右のメイン画像を結合してキャプチャ（YesCaptcha形式）"""
        try:
            import base64
            from PIL import Image
            import io
            
            # 全フレームから全ての画像を収集
            all_images = []
            
            for f in self.page.frames:
                try:
                    imgs = f.query_selector_all("img")
                    for img in imgs:
                        try:
                            box = img.bounding_box()
                            if not box or box['width'] < 50 or box['height'] < 50:
                                continue
                            
                            screenshot = img.screenshot()
                            if screenshot and len(screenshot) > 500:
                                all_images.append({
                                    'x': box['x'],
                                    'width': box['width'],
                                    'height': box['height'],
                                    'data': screenshot
                                })
                        except:
                            continue
                except:
                    continue
            
            if len(all_images) < 2:
                return None
            
            # X座標でソートして左右を判定
            all_images.sort(key=lambda x: x['x'])
            
            # 最も左の画像を左画像、最も右の画像を右画像とする
            left_data = all_images[0]
            right_data = all_images[-1]
            
            # 同じ画像を2回取得している場合は除外
            if len(all_images) >= 2 and all_images[0]['x'] != all_images[-1]['x']:
                left_img = left_data['data']
                right_img = right_data['data']
            else:
                # X座標が同じ場合、幅で判定
                all_images.sort(key=lambda x: x['width'])
                left_img = all_images[0]['data']  # 小さい方が左
                right_img = all_images[-1]['data']  # 大きい方が右
                left_data = all_images[0]
                right_data = all_images[-1]
            
            # 画像を結合
            left_pil = Image.open(io.BytesIO(left_img))
            right_pil = Image.open(io.BytesIO(right_img))
            
            # 高さを揃える（推奨: 200px）
            target_height = 200
            
            # 左画像をリサイズ
            left_ratio = target_height / left_pil.height
            left_new_width = int(left_pil.width * left_ratio)
            left_pil = left_pil.resize((left_new_width, target_height), Image.Resampling.LANCZOS)
            
            # 右画像をリサイズ
            right_ratio = target_height / right_pil.height
            right_new_width = int(right_pil.width * right_ratio)
            right_pil = right_pil.resize((right_new_width, target_height), Image.Resampling.LANCZOS)
            
            # 横に結合（推奨: 386x200、間にスペースなし）
            total_width = left_pil.width + right_pil.width
            
            combined = Image.new('RGB', (total_width, target_height), (255, 255, 255))
            combined.paste(left_pil, (0, 0))
            combined.paste(right_pil, (left_pil.width, 0))
            
            # JPEGとしてBase64に変換（120KB以下に収める）
            buffer = io.BytesIO()
            quality = 90
            combined.save(buffer, format='JPEG', quality=quality, optimize=True)
            
            # サイズチェック（120KB = 122880 bytes）
            while buffer.tell() > 120000 and quality > 50:
                buffer = io.BytesIO()
                quality -= 10
                combined.save(buffer, format='JPEG', quality=quality, optimize=True)
            
            b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return f"data:image/jpeg;base64,{b64}"
            
        except Exception as e:
            return None
            return None
    
    def _click_arrow_times(self, frame, target_index):
        """現在位置5から目標位置に移動（最短経路で）"""
        try:
            # 現在位置は5（6枚キャプチャ後）
            current_pos = 5
            
            if target_index == current_pos:
                print("  Already at target position")
                return True
            
            # 最短経路を計算（6画像で循環）
            # 右に進む場合の距離
            right_distance = (target_index - current_pos) % 6
            # 左に進む場合の距離
            left_distance = (current_pos - target_index) % 6
            
            if right_distance <= left_distance:
                clicks = right_distance
                direction = "right"
                arrow_selector = ".right-arrow, button[aria-label='次の画像を表示します']"
            else:
                clicks = left_distance
                direction = "left"
                arrow_selector = ".left-arrow, button[aria-label='前の画像を表示します']"
            
            if clicks == 0:
                return True
            
            for i in range(clicks):
                result = frame.evaluate(f'''
                    () => {{
                        const arrow = document.querySelector("{arrow_selector}");
                        if (arrow) {{
                            arrow.click();
                            return true;
                        }}
                        return false;
                    }}
                ''')
                
                if not result:
                    return False
                time.sleep(0.3)
            
            return True
            
        except Exception as e:
            return False
                
    def _click_submit_button(self, frame):
        """送信ボタンをクリック"""
        try:
            for f in self.page.frames:
                try:
                    result = f.evaluate('''
                        () => {
                            const buttons = document.querySelectorAll("button");
                            for (const btn of buttons) {
                                if (btn.innerText.includes("送信") || btn.innerText.toLowerCase().includes("submit")) {
                                    btn.click();
                                    return true;
                                }
                            }
                            return null;
                        }
                    ''')
                    if result:
                        return True
                except:
                    continue
            return False
        except:
            return False
    
    def _click_reload_button(self, frame):
        """再起動/もう一度試すボタンをクリックし、クイズ開始ボタンが出たらそれもクリック"""
        try:
            # まず「もう一度試してください」や再起動ボタンをクリック
            frame.evaluate('''
                () => {
                    const buttons = document.querySelectorAll("button");
                    for (const btn of buttons) {
                        const ariaLabel = btn.getAttribute("aria-label") || "";
                        const text = btn.innerText || "";
                        if (ariaLabel === "再起動" || 
                            ariaLabel === "reload" ||
                            text.includes("もう一度試してください") ||
                            text.includes("Try again")) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            ''')
            
            # クリック後、少し待ってから「クイズを開始する」ボタンを探す
            time.sleep(2)
            
            # 「クイズを開始する」ボタンが表示されたらクリック
            for _ in range(5):  # 最大5回チェック
                clicked = self._click_quiz_start_button_if_exists(frame)
                if clicked:
                    print("Clicked 'Start Quiz' button after reload")
                    time.sleep(2)
                    break
                time.sleep(1)
                
        except Exception as e:
            print(f"Error clicking reload button: {e}")
    
    def _click_quiz_start_button_if_exists(self, frame):
        """「クイズを開始する」ボタンが存在すればクリック"""
        try:
            # 全フレームで探す
            for f in self.page.frames:
                try:
                    # aria-labelで探す
                    btn = f.query_selector("button[aria-label='クイズを開始する']")
                    if btn and btn.is_visible():
                        btn.click()
                        return True
                    
                    # テキストで探す
                    buttons = f.query_selector_all("button")
                    for b in buttons:
                        try:
                            text = b.inner_text()
                            if "クイズを開始" in text and b.is_visible():
                                b.click()
                                return True
                        except:
                            continue
                except:
                    continue
            
            # JSでも試す
            for f in self.page.frames:
                try:
                    result = f.evaluate('''
                        () => {
                            const btn = document.querySelector("button[aria-label='クイズを開始する']");
                            if (btn) {
                                btn.click();
                                return true;
                            }
                            const buttons = document.querySelectorAll("button");
                            for (const b of buttons) {
                                if (b.innerText && b.innerText.includes("クイズを開始")) {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    ''')
                    if result:
                        return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def _get_captcha_question(self, frame):
        """キャプチャの問題文を取得"""
        try:
            # 全フレームから問題文を探す
            for f in self.page.frames:
                try:
                    # 複数のセレクタを試す
                    selectors = [
                        "h2[data-theme='home.title']",
                        "h2.sc-1io4bok-0",
                        "h2",
                        "[data-theme='game.challenge-instructions']",
                    ]
                    
                    for selector in selectors:
                        try:
                            elem = f.query_selector(selector)
                            if elem:
                                text = elem.inner_text().strip()
                                if text and len(text) > 5:
                                    return text
                        except:
                            continue
                except:
                    continue
            
            return None
        except Exception as e:
            print(f"Error getting question: {e}")
            return None
    
    def _check_captcha_complete(self):
        """キャプチャが完了したか確認"""
        try:
            # OTP入力フォームが出たら完了
            otp_input = self.page.query_selector("#cvf-input-code")
            if otp_input:
                return True
            
            # 成功メッセージを確認
            page_content = self.page.content().lower()
            if "hello" in page_content or "さん" in page_content:
                return True
            
            return False
        except:
            return False
    
    def _do_phone_verification(self):
        """電話番号認証を実行"""
        try:
            # 電話番号入力ページにいるか確認
            self.random_sleep(2, 3)
            
            # SMS-Activateから番号を取得
            phone_number = self.sms_get_number()
            if not phone_number:
                print("Failed to get phone number from SMS service")
                return False
            
            # 1. まず国コードのドロップダウンを選択
            print("Selecting country code...")
            self.select_country_dropdown()
            self.random_sleep(1, 2)
            
            # 2. 電話番号（国番号なし）を取得
            phone_for_input = self.get_phone_for_amazon()
            if not phone_for_input:
                print("Failed to format phone number")
                phone_for_input = phone_number  # フォールバック
            
            print(f"Phone number to enter (without country code): {phone_for_input}")
            
            try:
                # 電話番号入力フィールドを探す
                phone_input = self.page.locator("input[type='tel']").first
                if phone_input:
                    phone_input.click()
                    self.random_sleep(0.3, 0.6)
                    phone_input.fill("")  # クリア
                    self.random_sleep(0.2, 0.4)
                    
                    # 人間らしく入力
                    for char in phone_for_input:
                        phone_input.type(char, delay=random.randint(50, 150))
                    
                    print(f"Entered phone: {phone_for_input}")
            except Exception as e:
                print(f"Phone input error: {e}")
                return False
            
            self.random_sleep(1, 2)
            
            # 「携帯番号を追加する」などのボタンをクリック
            try:
                self.page.click("input[type='submit']")
            except:
                try:
                    self.page.click("button[type='submit']")
                except:
                    try:
                        self.page.click(".a-button-input")
                    except:
                        print("Could not find submit button for phone")
            
            # SMSを待機状態に設定
            self.sms_set_status(1)
            
            self.random_sleep(3, 5)
            
            # SMS認証コードを取得
            print("\x00STATUS:Waiting SMS", flush=True)
            print("Waiting for SMS code...")
            sms_code = self.sms_get_code(max_wait=120)
            
            if sms_code:
                print("\x00STATUS:Got SMS", flush=True)
                print(f"Got SMS code: {sms_code}")
                print("\x00STATUS:Entering SMS", flush=True)
                print(f"Entering SMS code: {sms_code}")
                self.human_type("#cvf-input-code", sms_code)
                self.random_sleep(1, 2)
                
                # 確認ボタンをクリック
                try:
                    self.human_click("input[type='submit']")
                except:
                    try:
                        self.human_click("button[type='submit']")
                    except:
                        self.human_click(".a-button-input")
                
                # 成功としてマーク
                self.sms_set_status(6)
                
                self.random_sleep(2, 4)
                return True
            else:
                print("Failed to get SMS code")
                # キャンセル
                self.sms_set_status(8)
                return False
                
        except Exception as e:
            print(f"Phone verification error: {e}")
            import traceback
            traceback.print_exc()
            if self.sms_activation_id:
                self.sms_set_status(8)  # キャンセル
            return False
    
    def run(self):
        """メイン実行
        
        Returns:
            tuple: (success: bool, error_status: str or None)
        """
        try:
            print("=" * 50)
            print(f"Site: {self.site} Mode: {self.mode}")
            print("=" * 50)
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            # ブラウザ起動
            print("\x00STATUS:Starting Task", flush=True)
            try:
                self.start_browser(headless=self.headless)
            except Exception as e:
                print(f"Browser start failed: {e}")
                return False, "Failed Browser"
            
            # ★ ストップチェック
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            
            success, error_status = self.do_signup()
            
            if success:
                print("NAVIGATION_COMPLETE")
                print("Account created successfully")
            
            return success, error_status
            
        except Exception as e:
            if self._stop_requested:
                print("Task stopped by user")
                return False, "Stopped"
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return False, "Failed Unknown"
        finally:
            self.close_browser(intentional=True)


def main():
    """エントリーポイント"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-data", required=True, help="Path to task data JSON file")
    args = parser.parse_args()
    
    try:
        with open(args.task_data, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
    except Exception as e:
        print(f"Failed to load task data: {e}", file=sys.stderr)
        return
    
    bot = AmazonSignup(task_data)
    success, error_status = bot.run()
    
    # エラーステータスがある場合は出力（GUIが読み取る）
    if error_status:
        print(f"SIGNUP_ERROR:{error_status}")
    
    print(f"Bot finished with success={success}")


if __name__ == "__main__":
    main()