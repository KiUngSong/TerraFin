"""Korean alias → ticker mapping.

Strict 1:1 — one official Korean reading of the listed company name per ticker.
Map is only consulted when query contains Hangul; pure English/numeric queries
go straight to Yahoo Finance.
"""

# Official Korean company name → ticker
KR_ALIASES: dict[str, str] = {
    # ── Mega cap tech
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "엔비디아": "NVDA",
    "알파벳": "GOOGL",
    "아마존": "AMZN",
    "메타플랫폼스": "META",
    "테슬라": "TSLA",
    "넷플릭스": "NFLX",
    "브로드컴": "AVGO",
    # ── Semis
    "티에스엠씨": "TSM",
    "에이에스엠엘": "ASML",
    "어플라이드머티리얼즈": "AMAT",
    "마이크론": "MU",
    "에이엠디": "AMD",
    "인텔": "INTC",
    "퀄컴": "QCOM",
    "텍사스인스트루먼트": "TXN",
    "마벨": "MRVL",
    "온세미컨덕터": "ON",
    "아날로그디바이스": "ADI",
    "램리서치": "LRCX",
    "시놉시스": "SNPS",
    "케이던스디자인": "CDNS",
    # ── Software
    "어도비": "ADBE",
    "세일즈포스": "CRM",
    "오라클": "ORCL",
    "시스코": "CSCO",
    "서비스나우": "NOW",
    "인튜이트": "INTU",
    "워크데이": "WDAY",
    "아틀라시안": "TEAM",
    "데이터독": "DDOG",
    "스노우플레이크": "SNOW",
    "팔란티어": "PLTR",
    "크라우드스트라이크": "CRWD",
    "지스케일러": "ZS",
    "옥타": "OKTA",
    "팔로알토네트웍스": "PANW",
    "포티넷": "FTNT",
    "트윌리오": "TWLO",
    "쇼피파이": "SHOP",
    "스포티파이": "SPOT",
    "유니티소프트웨어": "U",
    "로블록스": "RBLX",
    "유아이패스": "PATH",
    # ── EV / Auto
    "리비안": "RIVN",
    "루시드": "LCID",
    "포드": "F",
    "제네럴모터스": "GM",
    "토요타": "TM",
    "혼다": "HMC",
    "페라리": "RACE",
    "스텔란티스": "STLA",
    "니오": "NIO",
    "샤오펑": "XPEV",
    "리오토": "LI",
    # ── Finance
    "제이피모건체이스": "JPM",
    "골드만삭스": "GS",
    "모건스탠리": "MS",
    "뱅크오브아메리카": "BAC",
    "씨티그룹": "C",
    "웰스파고": "WFC",
    "비자": "V",
    "마스터카드": "MA",
    "페이팔": "PYPL",
    "블록": "SQ",
    "버크셔해서웨이": "BRK.B",
    "찰스슈왑": "SCHW",
    "블랙록": "BLK",
    "아메리칸익스프레스": "AXP",
    "에스앤피글로벌": "SPGI",
    "무디스": "MCO",
    # ── Pharma / health
    "존슨앤존슨": "JNJ",
    "화이자": "PFE",
    "모더나": "MRNA",
    "일라이릴리": "LLY",
    "노보노디스크": "NVO",
    "유나이티드헬스": "UNH",
    "애브비": "ABBV",
    "머크": "MRK",
    "써모피셔사이언티픽": "TMO",
    "다나허": "DHR",
    "암젠": "AMGN",
    "길리어드": "GILD",
    "버텍스파마슈티컬스": "VRTX",
    "리제네론": "REGN",
    "애보트": "ABT",
    "메드트로닉": "MDT",
    "스트라이커": "SYK",
    "보스턴사이언티픽": "BSX",
    "인튜이티브서지컬": "ISRG",
    "씨브이에스헬스": "CVS",
    # ── Consumer
    "코카콜라": "KO",
    "펩시코": "PEP",
    "맥도날드": "MCD",
    "스타벅스": "SBUX",
    "나이키": "NKE",
    "월트디즈니": "DIS",
    "프록터앤갬블": "PG",
    "유니레버": "UL",
    "필립모리스": "PM",
    "알트리아": "MO",
    "에스티로더": "EL",
    "엘브이엠에이치": "LVMUY",
    "치폴레": "CMG",
    "크래프트하인즈": "KHC",
    "코스트코": "COST",
    "월마트": "WMT",
    "타겟": "TGT",
    "홈디포": "HD",
    "로우스": "LOW",
    "달러트리": "DLTR",
    "달러제너럴": "DG",
    "베스트바이": "BBY",
    "에어비앤비": "ABNB",
    "부킹홀딩스": "BKNG",
    "익스피디아": "EXPE",
    "우버": "UBER",
    "리프트": "LYFT",
    "도어대시": "DASH",
    "핀듀오듀오": "PDD",
    "알리바바": "BABA",
    "제이디닷컴": "JD",
    "메이퇀": "MPNGY",
    # ── Energy / Industrial
    "엑손모빌": "XOM",
    "셰브론": "CVX",
    "코노코필립스": "COP",
    "옥시덴탈페트롤리움": "OXY",
    "슐럼버거": "SLB",
    "보잉": "BA",
    "록히드마틴": "LMT",
    "노스롭그루먼": "NOC",
    "알티엑스": "RTX",
    "캐터필러": "CAT",
    "디어": "DE",
    "허니웰": "HON",
    "지이에어로스페이스": "GE",
    "유니온퍼시픽": "UNP",
    "페덱스": "FDX",
    "유피에스": "UPS",
    "쓰리엠": "MMM",
    "에머슨": "EMR",
    # ── Real estate / utility
    "리얼티인컴": "O",
    "프로로지스": "PLD",
    "아메리칸타워": "AMT",
    "넥스트에라에너지": "NEE",
    # ── Korean stocks (KOSPI .KS / KOSDAQ .KQ)
    "삼성전자": "005930.KS",
    "에스케이하이닉스": "000660.KS",
    "엘지에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "셀트리온": "068270.KS",
    "카카오": "035720.KS",
    "네이버": "035420.KS",
    "포스코홀딩스": "005490.KS",
    "엘지화학": "051910.KS",
    "삼성에스디아이": "006400.KS",
    "현대모비스": "012330.KS",
    "케이비금융": "105560.KS",
    "신한지주": "055550.KS",
    "삼성생명": "032830.KS",
    "삼성물산": "028260.KS",
    "엘지전자": "066570.KS",
    "엘지": "003550.KS",
    "에스케이": "034730.KS",
    "한화에어로스페이스": "012450.KS",
    "한화솔루션": "009830.KS",
    "포스코퓨처엠": "003670.KS",
    "삼성화재": "000810.KS",
    "메리츠금융지주": "138040.KS",
    "하나금융지주": "086790.KS",
    "우리금융지주": "316140.KS",
    "현대중공업": "329180.KS",
    "두산에너빌리티": "034020.KS",
    "에스케이텔레콤": "017670.KS",
    "케이티": "030200.KS",
    "엘지유플러스": "032640.KS",
    "한국전력": "015760.KS",
    "한국가스공사": "036460.KS",
    "현대건설": "000720.KS",
    "삼성중공업": "010140.KS",
    "한미반도체": "042700.KS",
    "주성엔지니어링": "036930.KS",
    "에코프로비엠": "247540.KQ",
    "에코프로": "086520.KQ",
    "알테오젠": "196170.KQ",
    "에이치엘비": "028300.KQ",
    "리노공업": "058470.KQ",
    "셀트리온헬스케어": "091990.KQ",
    "엘앤에프": "066970.KQ",
    "펄어비스": "263750.KQ",
    "하이브": "352820.KS",
    "에스엠": "041510.KQ",
    "와이지엔터테인먼트": "122870.KQ",
    "제이와이피엔터테인먼트": "035900.KQ",
    "카카오뱅크": "323410.KS",
    "카카오페이": "377300.KS",
    "카카오게임즈": "293490.KQ",
    "두산밥캣": "241560.KS",
    "두산": "000150.KS",
    "에이치디현대중공업": "329180.KS",
    "씨제이제일제당": "097950.KS",
    "씨제이": "001040.KS",
    "오리온": "271560.KS",
    "농심": "004370.KS",
    "롯데쇼핑": "023530.KS",
    "이마트": "139480.KS",
    "신세계": "004170.KS",
    "쿠팡": "CPNG",
    "한온시스템": "018880.KS",
    "에스원": "012750.KS",
    "코오롱인더스트리": "120110.KS",
    "한국타이어": "161390.KS",
    "에프앤가이드": "064850.KQ",
}


def normalize_query(q: str) -> str:
    return q.strip().lower().replace(" ", "")


_NORMALIZED: dict[str, str] = {normalize_query(k): v for k, v in KR_ALIASES.items()}
# Reverse: ticker → original (display) Korean name, for showing alongside the ticker
_NORMALIZED_DISPLAY: dict[str, str] = {normalize_query(k): k for k in KR_ALIASES.keys()}


def lookup_kr_alias(query: str) -> str | None:
    """Return ticker for an exact alias match or None."""
    return _NORMALIZED.get(normalize_query(query))


def prefix_match_kr_aliases(query: str, limit: int = 8) -> list[tuple[str, str]]:
    """Return [(display_name, ticker), ...] for aliases starting with query.

    Exact matches rank first, then alphabetical prefix matches.
    """
    n = normalize_query(query)
    if not n:
        return []
    exact: list[tuple[str, str]] = []
    prefix: list[tuple[str, str]] = []
    for norm, ticker in _NORMALIZED.items():
        if norm == n:
            exact.append((_NORMALIZED_DISPLAY[norm], ticker))
        elif norm.startswith(n):
            prefix.append((_NORMALIZED_DISPLAY[norm], ticker))
    prefix.sort(key=lambda t: t[0])
    return (exact + prefix)[:limit]
