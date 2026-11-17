#!/usr/bin/env bash
# 一键创建本地固定签名证书：之后每次构建/更新 App 都保持同一签名，
# macOS TCC 授权（辅助功能/屏幕录制）不再因版本更新而失效。只需运行一次。
set -euo pipefail

CERT_NAME="WeChat Bot Local Signing"

if security find-identity -p codesigning -v | grep -q "$CERT_NAME"; then
  echo "✅ 证书已存在：$CERT_NAME（无需重复创建）"
  security find-identity -p codesigning -v | grep "$CERT_NAME"
  exit 0
fi

echo "将创建自签名代码签名证书「$CERT_NAME」（会弹出钥匙串授权框，输入登录密码即可）。"
echo "有效期 10 年，只存在你本机钥匙串中，不会上传任何地方。"
read -r -p "继续？[y/N] " confirm
[ "${confirm:-n}" = "y" ] || exit 1

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
CFG="$TMP_DIR/cert.cnf"
cat > "$CFG" <<CFGEOF
[req]
default_bits = 2048
distinguished_name = dn
prompt = no
[dn]
CN = $CERT_NAME
O = WeChat Bot
[ext]
basicConstraints = CA:false
keyUsage = digitalSignature
extendedKeyUsage = codeSigning
CFGEOF

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$TMP_DIR/key.pem" -out "$TMP_DIR/cert.pem" -days 3650 -config "$CFG" -extensions ext 2>/dev/null
PKCS12="$TMP_DIR/cert.p12"
openssl pkcs12 -export -out "$PKCS12" -inkey "$TMP_DIR/key.pem" -in "$TMP_DIR/cert.pem" -passout pass:tmp

security import "$PKCS12" -k ~/Library/Keychains/login.keychain-db -P tmp -T /usr/bin/codesign
# 设置 codesign 使用该证书时不再次询问
security set-key-partition-list -S apple-tool:,apple: -k "" "$CERT_NAME" 2>/dev/null || true

echo
echo "✅ 证书已创建。请在弹出的钥匙串访问框中允许 codesign 使用它（若出现）。"
echo "之后构建脚本会自动检测并使用「$CERT_NAME」固定签名。"
