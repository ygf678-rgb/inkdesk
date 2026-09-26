#!/usr/bin/env python3
"""英语晨卡推送：把 english/card.bmp（Mac 上按学习进度提前画好）盖上当天日期，推到 X3。
早上 5–11 点由 push.yml 调用（这段时间不推新闻屏）；手动测试：gh workflow run push.yml -f mode=english
卡的内容由 ~/inkclaude/english/morning_card.py 生成并提交，这里只负责「盖日期 + 上传 + 发刷新」。2026-09-26 建。
"""
import io, os, sys, json, time, datetime, requests
from PIL import Image, ImageDraw, ImageFont
BASE = os.path.dirname(os.path.abspath(__file__))
DEVICE_ID = os.environ.get('DEVICE_ID', '').strip()
HOST = 'https://airpage.yunhug.com'
MQTT_HOST, MQTT_PORT = 'mqtt-cn.uipcat.com', 1883
WD = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

def stamp(img):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    img = img.convert('L'); d = ImageDraw.Draw(img)
    head = f'今日英语 · {now.month} 月 {now.day} 日 {WD[now.weekday()]}'
    f = ImageFont.truetype(os.path.join(BASE, 'fonts', 'cjk.ttf'), 19)
    w = d.textlength(head, font=f)
    d.rectangle([(img.width - w) / 2 - 12, 4, (img.width + w) / 2 + 12, 32], fill=255)
    d.text(((img.width - w) / 2, 8), head, font=f, fill=0)
    return img.convert('1', dither=Image.NONE)

def push(img):
    b = io.BytesIO(); img.save(b, format='BMP')
    r = requests.post(f'{HOST}/api/device/{DEVICE_ID}/image', files={'image': ('fallback.bmp', b.getvalue(), 'image/bmp')}, timeout=40)
    return r, len(b.getvalue())

def notify():
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f'inkenglish-{int(time.time()) % 100000}')
    c.connect(MQTT_HOST, MQTT_PORT, 30); c.loop_start()
    i = c.publish(f'airpage/device/{DEVICE_ID}/refresh', json.dumps({'ts': int(time.time() * 1000)}), qos=0)
    i.wait_for_publish(timeout=15); time.sleep(1); c.loop_stop(); c.disconnect()
    return i.is_published()

if __name__ == '__main__':
    meta = json.load(open(os.path.join(BASE, 'english', 'card.json'), encoding='utf-8'))
    img = stamp(Image.open(os.path.join(BASE, 'english', 'card.bmp')))
    img.save(os.path.join(BASE, 'english', 'card_today.bmp'))
    print(f"晨卡：第 {meta['lesson']} 课第 {meta['day']} 天（{meta['made']} 生成）")
    if '--push' in sys.argv:
        if not DEVICE_ID: print('!! DEVICE_ID 未设置'); sys.exit(1)
        r, n = push(img); print(f'上传 HTTP {r.status_code}  {n} 字节  {r.text[:120]}')
        if not r.ok: sys.exit(1)
        try: print(f"MQTT {'已发送' if notify() else '失败'}")
        except Exception as e: print(f'MQTT 异常: {e}')
