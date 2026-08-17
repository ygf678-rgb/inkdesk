#!/usr/bin/env python3
"""
inkdesk (云端版) — 日期 / 老黄历 / 天气 / 今日选题，推到阅星瞳 X3。
跑在 GitHub Actions 上，不依赖本机。
待办已移除（本机数据云端读不到）；要闻已移除（2026-08-17 他要求整块换成选题）。
"""
import json, os, sys, time, io, datetime
from PIL import Image, ImageDraw, ImageFont
import requests

CITY       = "Guangzhou"
CITY_LABEL = "广州"
DEVICE_ID  = os.environ.get("DEVICE_ID", "").strip()
HOST       = "https://airpage.yunhug.com"
MQTT_HOST, MQTT_PORT = "mqtt-cn.uipcat.com", 1883
W, H       = 528, 792
BASE       = os.path.dirname(os.path.abspath(__file__))
CJK        = os.path.join(BASE, "fonts", "cjk.ttf")   # 由 workflow 运行时下载
WD         = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]

WC = {113:"晴",116:"多云",119:"阴",122:"阴天",143:"薄雾",176:"局部小雨",179:"局部小雪",
 182:"局部雨夹雪",185:"局部冻雨",200:"雷阵雨",227:"吹雪",230:"暴风雪",248:"雾",260:"冻雾",
 263:"小毛毛雨",266:"毛毛雨",281:"冻毛毛雨",284:"强冻毛毛雨",293:"局部小雨",296:"小雨",
 299:"局部中雨",302:"中雨",305:"局部大雨",308:"大雨",311:"冻雨",314:"强冻雨",317:"小雨夹雪",
 320:"中雪夹雨",323:"局部小雪",326:"小雪",329:"局部中雪",332:"中雪",335:"局部大雪",338:"大雪",
 350:"冰粒",353:"小阵雨",356:"中阵雨",359:"暴雨",362:"小阵雨夹雪",365:"中阵雨夹雪",368:"小阵雪",
 371:"中到大阵雪",374:"小冰粒",377:"中到大冰粒",386:"局部雷阵雨",389:"强雷阵雨",
 392:"局部雷阵雪",395:"中到大雷阵雪",
 149:"霾"}   # 149 是 wttr.in 自己加的码，不在 WWO 标准表里

# 码表没命中时按英文关键词兜底，别让英文原文漏上屏
DESC_KW = [("haze","霾"),("smok","烟霾"),("dust","浮尘"),("sand","沙尘"),
           ("thunder","雷雨"),("drizzle","毛毛雨"),("shower","阵雨"),("sleet","雨夹雪"),
           ("freez","冻雨"),("blizzard","暴风雪"),("snow","雪"),("rain","雨"),
           ("fog","雾"),("mist","薄雾"),("overcast","阴"),("cloud","多云"),
           ("clear","晴"),("sunny","晴")]

def zh_desc(code, en):
    """weatherCode → 中文；没命中就按英文关键词猜；再不行才回落英文"""
    try:
        z = WC.get(int(code))
        if z: return z
    except Exception:
        pass
    low = (en or "").lower()
    for k, z in DESC_KW:
        if k in low: return z
    return en or "—"

NEWS_API = "https://newsnow.busiyi.world/api/s"
NEWS_UA  = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
NEWS_SRC = [("thepaper", "澎湃新闻", 2), ("baidu", "百度热搜", 2), ("toutiao", "今日头条", 2)]

# ── 今日选题：自己查 PubMed（Kindle 那套的云端轻量版）──────────────
# 有 QWEN_KEY 就 AI 预筛 + 中文化；没有就只报条数，绝不把英文长标题塞上屏
QWEN_KEY    = os.environ.get("QWEN_KEY", "").strip()
AI_MODEL    = "qwen3.8-max"
AI_URL      = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
TOPIC_CACHE = os.path.join(BASE, "topics.json")   # 由 actions/cache 按日保留
PM_DAYS     = 7
N_A, N_B    = 5, 3        # 上屏配额：A 号 5 条、B 号 3 条
PM_SECTIONS = [
    ("A", "更年期",   "menopause"),
    ("A", "激素治疗", '"menopausal hormone therapy" OR "hormone replacement therapy"'),
    ("A", "骨质疏松", "osteoporosis AND postmenopausal"),
    ("A", "潮热",     '"vasomotor symptoms"'),
    ("A", "睡眠",     "menopause AND (sleep OR insomnia)"),
    ("A", "认知",     '(menopause OR estrogen) AND (cognition OR "cognitive decline")'),
    ("B", "犬行为",   "dog AND behavior"),
    ("B", "猫科疾病", "feline AND disease"),
    ("B", "宠物营养", "(dog OR cat) AND nutrition"),
    ("B", "人宠关系", '"human-animal bond" OR "pet ownership"'),
]

def F(s):
    try:    return ImageFont.truetype(CJK, s)
    except: return ImageFont.load_default()

def now_local():
    """Actions 跑在 UTC，显式换成东八区，不依赖 runner 的 TZ 设置。"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))

# ---------------- 数据 ----------------
def _fetch_weather():
    try:
        d = requests.get(f"https://wttr.in/{CITY}?format=j1", timeout=25).json()
        c = d["current_condition"][0]
        def desc(o):
            try:    en = o["weatherDesc"][0]["value"].strip()
            except: en = ""
            return zh_desc(o.get("weatherCode", 0), en)
        days = []
        for w in d["weather"][:3]:
            noon = w["hourly"][4] if len(w["hourly"]) > 4 else w["hourly"][0]
            days.append({"lo": w["mintempC"], "hi": w["maxtempC"],
                         "desc": desc(noon), "rain": noon.get("chanceofrain", "0")})
        return {"temp": c["temp_C"], "feels": c["FeelsLikeC"], "desc": desc(c),
                "hum": c["humidity"], "wind": c["windspeedKmph"], "days": days}
    except Exception as e:
        return {"error": type(e).__name__}

def get_weather():
    for i in range(3):
        r = _fetch_weather()
        if "error" not in r: return r
        if i < 2: time.sleep(4)
    return r

def get_news():
    out = []
    for sid, name, n in NEWS_SRC:
        titles = []
        for i in range(3):
            try:
                r = requests.get(NEWS_API, params={"id": sid}, timeout=25,
                                 headers={"User-Agent": NEWS_UA,
                                          "Referer": "https://newsnow.busiyi.world/"})
                items = r.json().get("items") or []
                titles = [x.get("title", "").strip() for x in items[:n] if x.get("title")]
                if titles: break
            except Exception:
                pass
            time.sleep(2)
        if titles: out.append((name, titles))
    return out

def _pm(path, params):
    r = requests.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{path}",
                     params=params, timeout=25, headers={"User-Agent": NEWS_UA})
    r.raise_for_status()
    return r

def _ai_pick(cands):
    """把候选交给千问，按配额挑，返回 [(账号, 中文标题)]"""
    lines = [f"{i+1}. [{a}] {t}\n{ab[:260]}" for i, (a, t, ab) in enumerate(cands)]
    prompt = ("我做两个短视频账号：A【更年期科普】面向 40-55 岁女性；B【宠物】面向养猫狗的人。\n"
              f"下面是最近的文献，挑出最值得做成短视频的：A 号 {N_A} 条、B 号 {N_B} 条。\n"
              "每条一行，严格用格式（不要别的任何内容）：账号|中文标题\n"
              "- 账号填 A 或 B\n"
              "- 🔴 两个号的条数必须凑满，别把名额都给 A\n"
              "- 中文标题不超过 22 字，说人话，别用学术腔\n"
              "- 优先挑有生活指导意义的；纯基础研究不要\n\n" + "\n\n".join(lines))
    r = requests.post(AI_URL, timeout=120,
        headers={"Authorization": f"Bearer {QWEN_KEY}", "Content-Type": "application/json"},
        json={"model": AI_MODEL, "max_tokens": 900, "enable_thinking": False,
              "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:                      # 日志里能看到原因，不会带出 key
        print(f"[topics] AI HTTP {r.status_code}: {r.text[:200]}")
        return []
    txt = r.json()["choices"][0]["message"]["content"]
    got = {"A": [], "B": []}
    for ln in txt.splitlines():
        p = ln.strip().split("|", 1)
        if len(p) == 2 and p[0].strip() in ("A", "B") and p[1].strip():
            got[p[0].strip()].append(p[1].strip())
    # 按配额裁；某个号不够就让另一个号补位，别留空行
    a, b = got["A"][:N_A], got["B"][:N_B]
    a += got["A"][N_A:N_A + (N_B - len(b))]
    b += got["B"][N_B:N_B + (N_A - len(a))]
    return [("A", t) for t in a] + [("B", t) for t in b]

def get_topics():
    """→ {'counts':{'A':n,'B':n}, 'secs':[(名,数)…], 'tops':[(账号,中文标题)…]}"""
    today = now_local().strftime("%Y%m%d")
    try:
        c = json.load(open(TOPIC_CACHE, encoding="utf8"))
        # 🔴 缓存里没有 tops 而现在又有 key，说明上次是没 key 时算的 —— 必须重算。
        #    否则当天第一次跑碰上缺 key，一整天都会返回那份空结果
        if c.get("date") == today and (c.get("tops") or not QWEN_KEY):
            return c
    except Exception:
        pass

    counts, secs, cands = {"A": 0, "B": 0}, [], []
    for acct, name, q in PM_SECTIONS:
        try:
            d = _pm("esearch.fcgi", {"db": "pubmed", "term": q, "reldate": PM_DAYS,
                    "datetype": "pdat", "retmax": 3, "retmode": "json",
                    "sort": "date"}).json()["esearchresult"]
        except Exception:
            continue
        n = int(d.get("count", 0))
        counts[acct] += n
        if n: secs.append((name, n))
        for pid in d.get("idlist", [])[:2]:
            cands.append((acct, name, pid))
        time.sleep(0.4)                      # NCBI 限 3 次/秒

    tops = []
    print(f"[topics] QWEN_KEY={'已配置' if QWEN_KEY else '缺失'} 候选={len(cands)} 命中={counts}")
    if QWEN_KEY and cands:
        try:
            ids = ",".join(c[2] for c in cands)
            xml = _pm("efetch.fcgi", {"db": "pubmed", "id": ids, "retmode": "xml"}).text
            import re as _re
            arts = _re.findall(r"<PubmedArticle>.*?</PubmedArticle>", xml, _re.S)
            pool = []
            for (acct, name, _), a in zip(cands, arts):
                t  = " ".join(_re.findall(r"<ArticleTitle[^>]*>(.*?)</ArticleTitle>", a, _re.S))
                ab = " ".join(_re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", a, _re.S))
                t  = _re.sub(r"<[^>]+>", "", t).strip()
                ab = _re.sub(r"<[^>]+>", "", ab).strip()
                if t: pool.append((acct, t, ab))
            if pool: tops = _ai_pick(pool)
            print(f"[topics] 送审 {len(pool)} 篇，AI 挑出 {len(tops)} 条")
        except Exception as e:
            print(f"[topics] AI 出错 {type(e).__name__}: {str(e)[:200]}")
            tops = []

    secs.sort(key=lambda s: -s[1])
    data = {"date": today, "counts": counts, "secs": secs[:6], "tops": tops}
    try:
        json.dump(data, open(TOPIC_CACHE, "w", encoding="utf8"), ensure_ascii=False)
    except Exception:
        pass
    return data

def huangli(dt):
    try:
        from lunar_python import Solar
        l = Solar.fromYmd(dt.year, dt.month, dt.day).getLunar()
        nj = l.getNextJieQi()
        d2 = datetime.date(*[int(x) for x in nj.getSolar().toYmd().split("-")])
        return {"nong": f"农历{l.getMonthInChinese()}月{l.getDayInChinese()}",
                "ganzhi": f"{l.getYearInGanZhi()}年 {l.getMonthInGanZhi()}月 {l.getDayInGanZhi()}日",
                "sx": l.getYearShengXiao(), "nayin": l.getDayNaYin(),
                "yi": l.getDayYi()[:7], "ji": l.getDayJi()[:6],
                "chong": l.getDayChongDesc(), "sha": l.getDaySha(),
                "shen": f"{l.getDayTianShen()} {l.getDayTianShenType()}",
                "jq": f"{nj.getName()} {d2.month}/{d2.day}", "jqd": (d2 - dt).days}
    except Exception as e:
        return {"err": type(e).__name__}

# ---------------- 绘制 ----------------
def render():
    now = now_local()
    img = Image.new("L", (W, H), 255); d = ImageDraw.Draw(img)
    d.rectangle([0,0,W-1,H-1], outline=0, width=2)

    def clip(s, px, fnt):
        while s and d.textlength(s, font=fnt) > px: s = s[:-1]
        return s

    TB = 34
    for yy in range(6, TB-6, 4): d.line([(6,yy),(W-7,yy)], fill=0, width=2)
    d.rectangle([2,2,W-3,TB], outline=0, width=2)
    d.rectangle([12,10,26,24], fill=255); d.rectangle([12,10,26,24], outline=0, width=2)
    t, f = now.strftime("%Y 年 %m 月"), F(18)
    tw = d.textlength(t, font=f)
    d.rectangle([(W-tw)/2-14,4,(W+tw)/2+14,TB-2], fill=255)
    d.text(((W-tw)/2, 9), t, font=f, fill=0)

    y = TB + 14

    # ---- 日期 + 干支 ----
    ds, df_ = str(now.day), F(84)
    d.text((24, y-10), ds, font=df_, fill=0)
    x = 24 + d.textlength(ds, font=df_) + 14
    d.text((x, y+8), WD[now.weekday()], font=F(30), fill=0)
    HL = huangli(now.date())
    if "err" not in HL:
        d.text((x, y+48), HL["nong"], font=F(20), fill=0)
        rx = W - 26
        for i, txt in enumerate([HL["ganzhi"], f"生肖{HL['sx']}  {HL['nayin']}",
                                 f"距{HL['jq']} {HL['jqd']}天"]):
            fnt = F(16 if i == 0 else 15)
            d.text((rx - d.textlength(txt, font=fnt), y + 2 + i*20), txt, font=fnt, fill=0)
    y += 88
    d.line([(22,y),(W-22,y)], fill=0, width=2); y += 12

    # ---- 宜忌 ----
    if "err" not in HL:
        for lab, key, inv in (("宜","yi",True), ("忌","ji",False)):
            bx, by, bs = 24, y, 22
            d.rectangle([bx,by,bx+bs,by+bs], fill=0 if inv else 255, outline=0, width=2)
            d.text((bx+4, by+1), lab, font=F(17), fill=255 if inv else 0)
            items = "  ".join(HL[key]) or "诸事不宜"
            fnt = F(16)
            while d.textlength(items, font=fnt) > W-78 and "  " in items:
                items = items.rsplit("  ", 1)[0]
            d.text((bx+bs+10, by+2), items, font=fnt, fill=0)
            y += 27
        d.text((24, y), f"冲{HL['chong']}  煞{HL['sha']}  值神{HL['shen']}", font=F(14), fill=0)
        y += 20
        d.line([(22,y),(W-22,y)], fill=0, width=2); y += 12

    # ---- 天气 ----
    w = get_weather()
    if "error" in w:
        d.text((24, y), "天气获取失败", font=F(15), fill=0); y += 28
    else:
        tf = F(56); ts = f"{w['temp']}°"
        d.text((24, y), ts, font=tf, fill=0)
        x = 24 + d.textlength(ts, font=tf) + 12
        d.text((x, y+6), w["desc"], font=F(26), fill=0)
        d.text((x, y+34), f"体感 {w['feels']}°   湿度 {w['hum']}%   风 {w['wind']}km/h",
               font=F(15), fill=0)
        y += 66
        for i, dd in enumerate(w["days"]):
            bx = 24 + i*((W-48)//3)
            d.text((bx, y), ["今天","明天","后天"][i], font=F(16), fill=0)
            d.text((bx, y+20), f"{dd['lo']}~{dd['hi']}°", font=F(20), fill=0)
            d.text((bx, y+42), dd["desc"], font=F(15), fill=0)
            if dd["rain"] and int(dd["rain"]) > 20:
                d.text((bx, y+58), f"降雨 {dd['rain']}%", font=F(14), fill=0)
        y += 80
    d.line([(22,y),(W-22,y)], fill=0, width=2); y += 14

    # ---- 今日选题（要闻已按他要求整块去掉，全给选题）----
    try:    tp = get_topics()
    except Exception: tp = None
    if tp and (tp["counts"]["A"] or tp["counts"]["B"]):
        d.text((24, y), "今日选题" if tp["tops"] else "近期新研究", font=F(21), fill=0)
        head = f"近{PM_DAYS}天 {tp['counts']['A'] + tp['counts']['B']} 篇新文献"
        d.text((W - 24 - d.textlength(head, font=F(15)), y + 6), head, font=F(15), fill=0)
        y += 30
        FOOT_TOP = H - 56
        if tp["tops"]:
            tf, sf = F(20), F(16)
            for acct, label in (("A", "A号 · 更年不惑"), ("B", "B号 · 宠物")):
                rows = [t for a, t in tp["tops"] if a == acct]
                if not rows or y > FOOT_TOP - 50: continue
                d.text((28, y), label, font=sf, fill=0); y += 24
                for t in rows:
                    if y > FOOT_TOP - 26: break
                    d.text((32, y), "· " + clip(t, W - 74, tf), font=tf, fill=0); y += 28
                y += 6
        else:
            line = " · ".join(f"{n}{c}" for n, c in tp["secs"][:4])
            d.text((30, y), clip(line, W - 60, F(16)), font=F(16), fill=0); y += 24

    # ---- 页脚 ----
    fy = H - 32
    d.line([(22, fy-12), (W-22, fy-12)], fill=0, width=2)
    d.text((24, fy), now.strftime("更新 %H:%M"), font=F(15), fill=0)
    d.text((W-24-d.textlength(CITY_LABEL, font=F(15)), fy), CITY_LABEL, font=F(15), fill=0)

    return img.convert("1", dither=Image.NONE)

# ---------------- 推送 ----------------
def push(img):
    b = io.BytesIO(); img.save(b, format="BMP"); data = b.getvalue()
    r = requests.post(f"{HOST}/api/device/{DEVICE_ID}/image",
                      files={"image": ("fallback.bmp", data, "image/bmp")}, timeout=40)
    return r, len(data)

def notify():
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"inkdesk-{int(time.time())%100000}")
    c.connect(MQTT_HOST, MQTT_PORT, 30); c.loop_start()
    i = c.publish(f"airpage/device/{DEVICE_ID}/refresh",
                  json.dumps({"ts": int(time.time()*1000)}), qos=0)
    i.wait_for_publish(timeout=15); time.sleep(1)
    c.loop_stop(); c.disconnect()
    return i.is_published()

if __name__ == "__main__":
    img = render()
    img.save("inkdesk.bmp"); img.convert("L").save("inkdesk.png")
    print(f"生成 {img.size}")
    if "--push" in sys.argv:
        if not DEVICE_ID:
            print("!! DEVICE_ID 未设置（在仓库 Settings → Secrets 里加）"); sys.exit(1)
        r, n = push(img)
        print(f"上传 HTTP {r.status_code}  {n} 字节  {r.text[:120]}")
        if not r.ok: sys.exit(1)
        try:    print(f"MQTT {'已发送' if notify() else '失败'}")
        except Exception as e: print(f"MQTT 异常: {e}")
