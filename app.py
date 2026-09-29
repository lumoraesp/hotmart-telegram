from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime
from html import escape
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
TELEGRAM_CHAT_ID_LIA = os.environ.get('TELEGRAM_CHAT_ID_LIA')

# Redis (Upstash) guarda o message_id de cada venda para apagar a mensagem se ela for cancelada.
# Na Vercel cada requisição pode rodar num processo novo, então memória local não serve.
# Sem essas variáveis o bot funciona normalmente, só não apaga a mensagem da venda cancelada.
REDIS_URL = os.environ.get('KV_REST_API_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
REDIS_TOKEN = os.environ.get('KV_REST_API_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
REDIS_EXPIRA_SEGUNDOS = 120 * 24 * 3600  # cobre prazo de reembolso e de chargeback

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
    data = request.get_json(silent=True)
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

        nome_produto = escape(str(produto.get('name', 'Produto')))
        preco = compra.get('price', {})
        valor_total = preco.get('value', 0)
        moeda = preco.get('currency_value') or 'BRL'
        transacao = str(compra.get('transaction', 'N/A'))
        nome_comprador = escape(str(comprador.get('name', 'N/A')))
        email_comprador = escape(str(comprador.get('email', 'N/A')))
        conta_html = escape(conta)

        valor_brl, cotacao = converter_para_brl(valor_total, moeda)

        if moeda.upper() != 'BRL':
            if valor_brl:
                linha_valor = f"💰 <b>Valor:</b> {escape(moeda)} {valor_total:.2f} ≈ R$ {valor_brl:.2f}\n"
            else:
                linha_valor = f"💰 <b>Valor:</b> {escape(moeda)} {valor_total:.2f}\n"
        else:
            linha_valor = f"💰 <b>Valor:</b> R$ {valor_total:.2f}\n"

        comissao = compra.get('commission', {}).get('value', None)
        linha_comissao = f"💵 <b>Minha parte:</b> R$ {comissao:.2f}\n" if comissao else ""

        agora = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')

        if evento in EVENTOS_APROVACAO:
            mensagem = (
                f"🎉 <b>NOVA VENDA NA HOTMART!</b>\n"
                f"🏪 <b>Conta:</b> {conta_html}\n\n"
                f"📦 <b>Produto:</b> {nome_produto}\n"
                f"{linha_valor}"
                f"{linha_comissao}"
                f"👤 <b>Comprador:</b> {nome_comprador}\n"
                f"📧 <b>Email:</b> {email_comprador}\n"
                f"🔑 <b>Transação:</b> {escape(transacao)}\n"
                f"🕐 <b>Data:</b> {agora}"
            )
            message_id = enviar_telegram(mensagem, TELEGRAM_CHAT_ID)
            if message_id:
                redis_comando('SET', f'venda:{transacao}', message_id, 'EX', REDIS_EXPIRA_SEGUNDOS)

        elif evento in EVENTOS_CANCELAMENTO:
            emoji, label = LABELS_EVENTO.get(evento, ('❌', 'VENDA CANCELADA'))

            message_id = redis_comando('GETDEL', f'venda:{transacao}')
            if message_id:
                deletar_mensagem(message_id)

            mensagem = (
                f"{emoji} <b>{label}</b>\n"
                f"🏪 <b>Conta:</b> {conta_html}\n\n"
                f"📦 <b>Produto:</b> {nome_produto}\n"
                f"{linha_valor}"
                f"👤 <b>Comprador:</b> {nome_comprador}\n"
                f"📧 <b>Email:</b> {email_comprador}\n"
                f"🔑 <b>Transação:</b> {escape(transacao)}\n"
                f"🕐 <b>Data:</b> {agora}"
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
        'parse_mode': 'HTML'
    }
    response = requests.post(url, json=payload, timeout=10)
    data = response.json()
    if data.get('ok'):
        return data['result']['message_id']
    print(f"Telegram recusou a mensagem: {data.get('description')}")
    return None


def deletar_mensagem(message_id):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'message_id': int(message_id)
    }
    requests.post(url, json=payload, timeout=10)


def redis_comando(*comando):
    if not (REDIS_URL and REDIS_TOKEN):
        return None
    try:
        resp = requests.post(
            REDIS_URL,
            headers={'Authorization': f'Bearer {REDIS_TOKEN}'},
            json=[str(parte) for parte in comando],
            timeout=5,
        )
        return resp.json().get('result')
    except Exception as e:
        print(f"Erro no Redis: {e}")
        return None


@app.route('/webhook/lia', methods=['GET', 'POST'])
def lia_webhook():
    # Provisório: a Lia não documenta o formato do webhook. O payload vai para o log da Vercel
    # e o grupo recebe os campos reconhecíveis. Depois do primeiro evento real, trocar por
    # formatação específica e remover o print (tem dado pessoal do aluno).
    corpo = request.get_data(as_text=True)
    print(f"LIA_PAYLOAD method={request.method} args={dict(request.args)} "
          f"content_type={request.content_type} body={corpo[:8000]}")

    data = request.get_json(silent=True)
    if not isinstance(data, (dict, list)):
        return jsonify({'status': 'ignorado'}), 200

    linhas = [f"{escape(chave)}: {escape(str(valor))}" for chave, valor in campos_relevantes(data)]
    agora = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M')
    mensagem = "💰 <b>BOLETO PAGO NA LIA</b>\n\n" + "\n".join(linhas[:15]) + f"\n\n🕐 {agora}"
    enviar_telegram(mensagem, TELEGRAM_CHAT_ID_LIA)
    return jsonify({'status': 'ok'}), 200


PALAVRAS_RELEVANTES = ('name', 'nome', 'email', 'product', 'produto', 'amount', 'value', 'valor',
                       'price', 'installment', 'parcela', 'number', 'paid', 'pago', 'due', 'status')


def campos_relevantes(dado, prefixo=''):
    if isinstance(dado, dict):
        for chave, valor in dado.items():
            yield from campos_relevantes(valor, f"{prefixo}{chave}.")
    elif isinstance(dado, list):
        for i, valor in enumerate(dado[:3]):
            yield from campos_relevantes(valor, f"{prefixo}{i}.")
    elif dado not in (None, '') and any(p in prefixo.lower() for p in PALAVRAS_RELEVANTES):
        yield prefixo.rstrip('.'), dado


@app.route('/', methods=['GET'])
def home():
    return jsonify({'status': 'Servidor rodando!'}), 200


if __name__ == '__main__':
    porta = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=porta)
