#!/bin/bash
# ============================================================================
# BinanceTR Trade Scanner - VPS Kurulum Scripti
# ============================================================================
# Kullanım: bash setup-vps.sh
# ============================================================================

set -e

APP_DIR="/home/trader/trade"
SERVICE_NAME="trade-scanner"
USER_NAME="trader"

echo "================================================"
echo "  BinanceTR Scanner - VPS Kurulum"
echo "================================================"

# 1. Sistem güncellemesi
echo "[1/7] Sistem güncelleniyor..."
sudo apt update && sudo apt upgrade -y

# 2. Python ve gerekli paketler
echo "[2/7] Python kuruluyor..."
sudo apt install -y python3 python3-pip python3-venv git

# 3. Kullanıcı oluştur (yoksa)
echo "[3/7] Kullanıcı kontrol ediliyor..."
if ! id "$USER_NAME" &>/dev/null; then
    sudo useradd -m -s /bin/bash "$USER_NAME"
    echo "  '$USER_NAME' kullanıcısı oluşturuldu."
else
    echo "  '$USER_NAME' kullanıcısı zaten var."
fi

# 4. Proje dosyalarını kopyala
echo "[4/7] Proje kuruluyor..."
sudo mkdir -p "$APP_DIR"
sudo cp -r ../*.py ../requirements.txt "$APP_DIR/"
sudo chown -R "$USER_NAME:$USER_NAME" "$APP_DIR"

# 5. Python sanal ortam ve bağımlılıklar
echo "[5/7] Python bağımlılıkları kuruluyor..."
sudo -u "$USER_NAME" bash -c "
    cd $APP_DIR
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
"

# 6. .env dosyası oluştur (eğer yoksa)
echo "[6/7] Konfigürasyon kontrol ediliyor..."
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    sudo -u "$USER_NAME" bash -c "cat > $ENV_FILE << 'ENVEOF'
# Telegram Bot Ayarları
TELEGRAM_BOT_TOKEN=BURAYA_BOT_TOKEN_YAZIN
TELEGRAM_CHAT_ID=BURAYA_CHAT_ID_YAZIN

# BinanceTR API Ayarları (sadece okuma izni yeterli)
BINANCE_API_KEY=BURAYA_API_KEY_YAZIN
BINANCE_API_SECRET=BURAYA_API_SECRET_YAZIN
ENVEOF"
    sudo chmod 600 "$ENV_FILE"
    echo "  .env dosyası oluşturuldu. Lütfen düzenleyin: nano $ENV_FILE"
else
    echo "  .env dosyası zaten var."
fi

# 7. Systemd servisi kur
echo "[7/7] Servis kuruluyor..."
sudo cp trade-scanner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "================================================"
echo "  KURULUM TAMAMLANDI!"
echo "================================================"
echo ""
echo "Sonraki adımlar:"
echo "  1. API anahtarlarını girin:"
echo "     sudo nano $ENV_FILE"
echo ""
echo "  2. Botu başlatın:"
echo "     sudo systemctl start $SERVICE_NAME"
echo ""
echo "  3. Logları izleyin:"
echo "     sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "  4. Durumu kontrol edin:"
echo "     sudo systemctl status $SERVICE_NAME"
echo ""
echo "  5. Telegram test:"
echo "     cd $APP_DIR && source venv/bin/activate && python scanner.py --test"
echo ""
