@echo off
rem สร้างไฟล์ .exe แจกได้โดยไม่ต้องลง Python
rem ผลลัพธ์อยู่ที่ dist\AndroidCast.exe (scrcpy จะถูกดาวน์โหลดอัตโนมัติตอนรันครั้งแรก)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name AndroidCast app.py
echo.
echo เสร็จแล้ว -> dist\AndroidCast.exe
pause
