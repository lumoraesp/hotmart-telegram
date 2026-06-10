from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


@app.route('/webhook/hotmart', methods=['POST'])
def hotmart_webhook():
    data = request.json

    if not data:
        return jsonify({'erro': 'Sem dados recebidos'}), 400

    evento = data.get('event', '')

    if evento not in ['PURCHASE_APPROVED', 'PURCHASE_COMPLETE']:
        return jsonify({'status': 'ignorado', 'evento': evento}), 200

    try:
        purchase_data = data.get('data', {})
        produto = purchase_data.get('product', {})
        compra = purchase_data.get('purchase', {})
        comprador = purchase_data.get('buyer', {})

        nome_produto = produto.get('name', 'Produto')
        valor_total = compra.get('price', {}).get('value', 0)
        transacao = compra.get('transaction', 'N/A')
        nome_comprador = comprador.get('name', 'N/A')
        email_comprador = comprador.get('email', 'N/A')

        comissao = compra.get('commission', {}).get('value', None)
        linha_comissao = f"💵 *Minha parte:* R$ {comissao:.2f}\n" if comissao else ""

        agora = datetime.now().strftime('%d/%m/%Y às %H:%M')

        mensagem = (
            f"🎉 *NOVA VENDA NA HOTMART!*\n\n"
            f"📦 *Produto:* {nome_produto}\n"
            f"💰 *Valor total:* R$ {valor_total:.2f}\n"
            f"{linha_comissao}"
            f"👤 *Comprador:* {nome_comprador}\n"
            f"📧 *Email:* {email_comprador}\n"
            f"🔑 *Transação:* {transacao}\n"
            f"🕐 *Data:* {agora}"
        )

        enviar_telegram(mensagem)
        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f"Erro ao processar venda: {e}")
        return jsonify({'erro': str(e)}), 500


def enviar_telegram(mensagem):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensagem,
        'parse_mode': 'Markdown'
    }
    requests.post(url, json=payload, timeout=10)


@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'Servidor rodando!'}), 200


if __name__ == '__main__':
    porta = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=porta)
