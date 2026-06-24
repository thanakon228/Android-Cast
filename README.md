# 📡 Android Cast

> แคสหน้าจอมือถือ **Android ขึ้นหน้าต่างบน PC แบบไร้สาย** — หน้าตาและการเชื่อมต่อสไตล์ **TikTok Live**

โปรแกรมนี้เขียนด้วย **Python + PyQt6** ครอบ [scrcpy](https://github.com/Genymobile/scrcpy) + adb ไว้
จุดเด่นคือ **ดาวน์โหลด scrcpy ให้อัตโนมัติ** ตอนเปิดครั้งแรก คุณไม่ต้องติดตั้ง scrcpy หรือ adb เอง

<p align="center">
  <em>เชื่อมต่อครั้งเดียว → ครั้งต่อไปกดปุ่มเดียวแคสได้เลย</em>
</p>

---

## ✨ ฟีเจอร์

- 🔌 **ดาวน์โหลด scrcpy + adb อัตโนมัติ** (~15MB) — ไม่ต้องตั้งค่าอะไรเอง
- 📶 **เชื่อมต่อไร้สาย** ผ่าน Wireless debugging (Android 11+) ด้วยรหัสจับคู่ 6 หลัก
- ⚡ **เชื่อมต่อด่วน** — จำอุปกรณ์ล่าสุด ครั้งต่อไปกดปุ่มเดียวจบ
- 🔌 **โหมด USB** สำรอง — เสียบครั้งเดียวแล้วสลับมาไร้สายอัตโนมัติ (รองรับ Android เก่ากว่า 11)
- 🎨 UI ธีมดำ-ชมพู สไตล์ TikTok Live

---

## 📋 สิ่งที่ต้องมีก่อน (Requirements)

| รายการ | รายละเอียด |
|--------|-----------|
| ระบบปฏิบัติการ | Windows 10/11 (64-bit) |
| Python | เวอร์ชัน **3.10 ขึ้นไป** ([ดาวน์โหลด](https://www.python.org/downloads/)) |
| มือถือ | Android (แนะนำ **11 ขึ้นไป** สำหรับเชื่อมไร้สายล้วน) |
| เครือข่าย | มือถือกับ PC ต้องอยู่ **WiFi วงเดียวกัน** |

> 💡 ตอนติดตั้ง Python อย่าลืมติ๊ก **"Add Python to PATH"**

---

## 🚀 การติดตั้ง

### 1. โคลนโปรเจกต์
```bash
git clone https://github.com/thanakon228/Android-Cast.git
cd Android-Cast
```

### 2. สร้าง virtual environment + ติดตั้งไลบรารี
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. เปิดโปรแกรม
```bash
python app.py
```
หรือดับเบิลคลิกที่ไฟล์ **`run.bat`** ได้เลย

> ⏳ เปิดครั้งแรกโปรแกรมจะดาวน์โหลด scrcpy อัตโนมัติ รอจนแถบสถานะขึ้นสีเขียว **"พร้อมใช้งาน"**

---

## 📱 วิธีใช้งาน

### โหมด WiFi (ไร้สาย) — Android 11 ขึ้นไป ✅ แนะนำ
1. มือถือ → **Settings → About phone** → แตะ **Build number** 7 ครั้ง (เพื่อเปิด Developer options)
2. **Settings → Developer options → Wireless debugging** → เปิด
3. แตะ **"Pair device with pairing code"** → จะได้ `IP:PORT` และ **รหัส 6 หลัก**
4. กรอกลงในโปรแกรม แล้วกด **"จับคู่ & เชื่อมต่อ & แคส"**
5. หน้าจอมือถือเด้งขึ้นมาเป็นหน้าต่างบน PC 🎉

ครั้งต่อ ๆ ไป โปรแกรมจะจำไว้ → กดปุ่ม **"เชื่อมต่อด่วน"** ปุ่มเดียวจบ

### โหมด USB — สำหรับ Android เก่ากว่า 11
1. เปิด **Developer options → USB debugging**
2. เสียบสาย USB → กด **"Allow"** บนมือถือ
3. กด **"ตรวจหาอุปกรณ์ USB"** → **"เปิดไร้สาย & แคสเลย"**
4. ถอดสายได้เลย ใช้งานไร้สายต่อ

---

## ⚠️ ข้อควรรู้

- scrcpy/adb **จำเป็นต้องเปิด Developer options ครั้งแรกเสมอ** — เลี่ยงไม่ได้
  หากต้องการแคสโดยไม่แตะ Developer options เลย ต้องเขียนแอปฝั่ง Android เองที่ใช้ MediaProjection API (เป็นคนละแนวทาง)
- มือถือกับ PC ต้องอยู่ **WiFi วงเดียวกัน**
- การเชื่อมไร้สายล้วน (pairing code) ต้องใช้ **Android 11 ขึ้นไป**

---

## 🛠️ การปรับความลื่น/คุณภาพ

แก้ในไฟล์ `app.py` เมธอด `_launch_mirror` ที่ตัวแปร `extra=[...]`:

| ออปชัน | ความหมาย |
|--------|----------|
| `--video-bit-rate 8M` | ปรับ bitrate (ลดลงถ้าเน็ตช้า) |
| `--max-fps 60` | จำกัดเฟรมเรต |
| `--max-size 1280` | ย่อความละเอียดให้ลื่นขึ้น (เพิ่มเองได้) |

---

## 📁 โครงสร้างไฟล์

```
Android-Cast/
├─ app.py              # หน้าต่างหลัก (PyQt6)
├─ scrcpy_manager.py   # ดาวน์โหลด/เรียก scrcpy + adb
├─ settings_store.py   # จำอุปกรณ์ล่าสุด
├─ run.bat             # ดับเบิลคลิกเปิด
├─ requirements.txt    # ไลบรารีที่ต้องใช้
├─ tools/              # scrcpy + adb (โหลดอัตโนมัติ — ไม่อยู่ใน repo)
└─ settings.json       # ถูกสร้างหลังเชื่อมต่อครั้งแรก
```

---

## 📜 License & เครดิต

โปรแกรมนี้ใช้ [scrcpy](https://github.com/Genymobile/scrcpy) (Apache-2.0) ของ Genymobile เป็นเครื่องยนต์เบื้องหลัง
