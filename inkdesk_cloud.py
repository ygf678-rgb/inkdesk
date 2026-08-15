#!/usr/bin/env python3
"""
inkdesk (云端版) — 日期 / 老黄历 / 天气 / 要闻，推到阅星瞳 X3。
跑在 GitHub Actions 上，不依赖本机。待办已移除（本机数据云端读不到）。
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
 392:"局部雷阵雪",395:"中到大雷阵雪"}

NEWS_API = "https://newsnow.busiyi.world/api/s"
NEWS_UA  = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
NEWS_SRC = [("thepaper", "澎湃新闻", 4), ("baidu", "百度热搜", 4), ("toutiao", "今日头条", 4)]

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
            try:    return WC.get(int(o.get("weatherCode", 0)), o["weatherDesc"][0]["value"].strip())
            except: return o["weatherDesc"][0]["value"].strip()
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
        d.text((x, y+48), HL["nong"], font=F(17), fill=0)
        rx = W - 26
        for i, txt in enumerate([HL["ganzhi"], f"生肖{HL['sx']}  {HL['nayin']}",
                                 f"距{HL['jq']} {HL['jqd']}天"]):
            fnt = F(14 if i == 0 else 13)
            d.text((rx - d.textlength(txt, font=fnt), y + 2 + i*20), txt, font=fnt, fill=0)
    y += 88
    d.line([(22,y),(W-22,y)], fill=0, width=2); y += 12

    # ---- 宜忌 ----
    if "err" not in HL:
        for lab, key, inv in (("宜","yi",True), ("忌","ji",False)):
            bx, by, bs = 24, y, 22
            d.rectangle([bx,by,bx+bs,by+bs], fill=0 if inv else 255, outline=0, width=2)
            d.text((bx+4, by+1), lab, font=F(15), fill=255 if inv else 0)
            items = "  ".join(HL[key]) or "诸事不宜"
            fnt = F(14)
            while d.textlength(items, font=fnt) > W-78 and "  " in items:
                items = items.rsplit("  ", 1)[0]
            d.text((bx+bs+10, by+2), items, font=fnt, fill=0)
            y += 27
        d.text((24, y), f"冲{HL['chong']}  煞{HL['sha']}  值神{HL['shen']}", font=F(12), fill=0)
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
        d.text((x, y+6), w["desc"], font=F(22), fill=0)
        d.text((x, y+34), f"体感 {w['feels']}°   湿度 {w['hum']}%   风 {w['wind']}km/h",
               font=F(13), fill=0)
        y += 66
        for i, dd in enumerate(w["days"]):
            bx = 24 + i*((W-48)//3)
            d.text((bx, y), ["今天","明天","后天"][i], font=F(14), fill=0)
            d.text((bx, y+20), f"{dd['lo']}~{dd['hi']}°", font=F(17), fill=0)
            d.text((bx, y+42), dd["desc"], font=F(13), fill=0)
            if dd["rain"] and int(dd["rain"]) > 20:
                d.text((bx, y+58), f"降雨 {dd['rain']}%", font=F(12), fill=0)
        y += 80
    d.line([(22,y),(W-22,y)], fill=0, width=2); y += 14

    # ---- 要闻热点 ----
    d.text((24, y), "要闻热点", font=F(17), fill=0); y += 26
    news = get_news()
    NEWS_MAX = H - 66
    if not news:
        d.text((30, y), "（热榜获取失败）", font=F(14), fill=0)
    else:
        nf = F(15)
        for name, titles in news:
            if y > NEWS_MAX - 40: break
            d.text((30, y), name, font=F(13), fill=0); y += 19
            for t in titles:
                if y > NEWS_MAX: break
                d.text((34, y), "· " + clip(t, W-90, nf), font=nf, fill=0); y += 21
            y += 4

    # ---- 页脚 ----
    fy = H - 32
    d.line([(22, fy-12), (W-22, fy-12)], fill=0, width=2)
    d.text((24, fy), now.strftime("更新 %H:%M"), font=F(14), fill=0)
    d.text((W-24-d.textlength(CITY_LABEL, font=F(14)), fy), CITY_LABEL, font=F(14), fill=0)

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
