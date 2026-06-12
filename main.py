from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def converter_para_brl(valor, moeda):
    if not moeda or moeda.upper() == 'BRL':
        return valor, None
    try:
        par = f"{moeda.upper()}-BRL"
        resp = requests.get(f"https://economia.awesomeapi.com.br/json/last/{par}", timeout=5)
        cotacao = float(resp.json()[f"{moeda.upper()}BRL"]['bid'])
        return round(valor * cotacao, 2), cotacao
    except Exception:
        return None, None

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
TELEGRAM_CHAT_ID_PROBLEMAS = os.environ.get('TELEGRAM_CHAT_ID_PROBLEMAS')

mensagens_enviadas = {}

EVENTOS_APROVACAO = ['PURCHASE_APPROVED', 'PURCHASE_COMPLETE']
EVENTOS_CANCELAMENTO = ['PURCHASE_CANCELED', 'PURCHASE_REFUNDED', 'PURCHASE_CHARGEBACK', 'PURCHASE_PROTEST', 'PURCHASE_EXPIRED']

LABELS_EVENTO = {
    'PURCHASE_CANCELED':  ('❌', 'VENDA CANCELADA'),
    'PURCHASE_REFUNDED':  ('↩️', 'VENDA REEMBOLSADA'),
    'PURCHASE_CHARGEBACK': ('🚨', 'CHARGEBACK'),
    'PURCHASE_PROTEST':   ('⚠️', 'VENDA PROTESTADA'),
    'PURCHASE_EXPIRED':   ('⏰', 'PAGAMENTO EXPIRADO'),
}


@app.route('/webhook/hotmart', methods=['POST'])
def hotmart_webhook():
    data = request.json
    conta = request.args.get('conta', 'Hotmart')

    if not data:
        return jsonify({'erro': 'Sem dados recebidos'}), 400

    evento = data.get('event', '')

    if evento not in EVENTOS_APROVACAO + EVENTOS_CANCELAMENTO:
        return jsonify({'status': 'ignorado', 'evento': evento}), 200

    try:
        purchase_data = data.get('data', {})
        produto = purchase_data.get('product', {})
        compra = purchase_data.get('purchase', {})
        comprador = purchase_data.get('buyer', {})

        nome_produto = produto.get('name', 'Produto')
        preco = compra.get('price', {})
        valor_total = preco.get('value', 0)
        moeda = preco.get('currency_value', 'BRL')
        transacao = compra.get('transaction', 'N/A')
        nome_comprador = comprador.get('name', 'N/A')
        email_comprador = comprador.get('email', 'N/A')

        valor_brl, cotacao = converter_para_brl(valor_total, moeda)

        if moeda.upper() != 'BRL':
            if valor_brl:
                linha_valor = f"💰 *Valor:* {moeda} {valor_total:.2f} ≈ R$ {valor_brl:.2f}\n"
            else:
                linha_valor = f"💰 *Valor:* {moeda} {valor_total:.2f}\n"
        else:
            linha_valor = f"💰 *Valor:* R$ {valor_total:.2f}\n"

        comissao = compra.get('commission', {}).get('value', None)
        linha_comissao = f"💵 *Minha parte:* R$ {comissao:.2f}\n" if comissao else ""

        agora = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')

        if evento in EVENTOS_APROVACAO:
            mensagem = (
                f"🎉 *NOVA VENDA NA HOTMART!*\n"
                f"🏪 *Conta:* {conta}\n\n"
                f"📦 *Produto:* {nome_produto}\n"
                f"{linha_valor}"
                f"{linha_comissao}"
                f"👤 *Comprador:* {nome_comprador}\n"
                f"📧 *Email:* {email_comprador}\n"
                f"🔑 *Transação:* {transacao}\n"
                f"🕐 *Data:* {agora}"
            )
            message_id = enviar_telegram(mensagem, TELEGRAM_CHAT_ID)
            if message_id:
                mensagens_enviadas[transacao] = message_id

        elif evento in EVENTOS_CANCELAMENTO:
            emoji, label = LABELS_EVENTO.get(evento, ('❌', 'VENDA CANCELADA'))

            if transacao in mensagens_enviadas:
                deletar_mensagem(mensagens_enviadas.pop(transacao))

            mensagem = (
                f"{emoji} *{label}*\n"
                f"🏪 *Conta:* {conta}\n\n"
                f"📦 *Produto:* {nome_produto}\n"
                f"{linha_valor}"
                f"👤 *Comprador:* {nome_comprador}\n"
                f"📧 *Email:* {email_comprador}\n"
                f"🔑 *Transação:* {transacao}\n"
                f"🕐 *Data:* {agora}"
            )
            enviar_telegram(mensagem, TELEGRAM_CHAT_ID_PROBLEMAS)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f"Erro ao processar evento: {e}")
        return jsonify({'erro': str(e)}), 500


def enviar_telegram(mensagem, chat_id):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': mensagem,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, json=payload, timeout=10)
    data = response.json()
    if data.get('ok'):
        return data['result']['message_id']
    return None


def deletar_mensagem(message_id):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'message_id': message_id
    }
    requests.post(url, json=payload, timeout=10)


@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'Servidor rodando!'}), 200


if __name__ == '__main__':
    porta = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=porta)
