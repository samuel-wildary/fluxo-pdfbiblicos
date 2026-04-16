import json
import os

path = r"c:\Users\Samuel Wildary\Desktop\robo\app\data\flow_config.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

new_tools = [
    {
        "kind": "text",
        "content": "Perfeito então!! Estou preparando tudo pra te enviar agora, e logo depois te passo os dados pra pagar. 💕\n\nSó peço seu compromisso de fazer o Pagamento depois para não deixar meu trabalho prejudicado, combinado? 😊",
        "label": "Preparando entrega"
    },
    {
        "kind": "media",
        "asset": "jogo-uno-da-fe_.pdf",
        "label": "PDF Uno da Fé"
    },
    {
        "kind": "media",
        "asset": "1.mp4",
        "caption": "Como são MUITOS JOGOS, eu criei uma pasta com todos os PDF’s, tá bom?\n\nBasta clicar no link abaixo para acessar, ver e baixar todo o material:\n👇🏻👇🏻👇🏻\n\nhttps://drive.google.com/drive/folders/14KYzeZ-k95nCA7uBwe0meHgWELGOF7oh?usp=sharing\n\n🚨 ATENÇÃO: Se o link não estiver aparecendo, basta salvar meu contato e enviar uma mensagem que o link da pasta com todo material vai ficar clicável...\nCombinado?",
        "label": "Vídeo da pasta com os PDFs"
    },
    {
        "kind": "text",
        "content": "Prontinho, já te enviei tudo, conforme o combinado, espero que goste, tá bom? 🥰",
        "label": "Confirmação de envio"
    },
    {
        "kind": "text",
        "content": "Agora é com você 💛\nVou te mandar um último áudio, e já passo os dados do pagamento 🙏",
        "label": "Aviso do áudio"
    },
    {
        "kind": "media",
        "asset": "3.ogg",
        "label": "Áudio 3 do pagamento"
    },
    {
        "kind": "text",
        "content": "💰 DADOS DE PAGAMENTO:\n\nChave Pix CNPJ: 65950121000140\n\n*VALORES:\n\nR$10,00 🤍 Contribuição mínima – acesso aos Jogos Bíblicos\n\nR$15,00 🌼 Contribuição recomendada – ajuda a manter e criar novos materiais cristãos\n\nR$25,00 💛 Contribuição especial – apoia ainda mais o projeto\n\nR$30,00 🌟 Contribuição abençoada – além de fortalecer sua casa, ajuda na montagem de cestas básicas para outras famílias",
        "label": "Dados de pagamento"
    },
    {
        "kind": "text",
        "content": "O pagamento vai aparecer no nome do meu filho:\n\n* Eduardo Estrello💛\n\nEle é quem me auxilia na parte financeira e na organização do projeto 🥰",
        "label": "Nome do pagamento"
    },
    {
        "kind": "text",
        "content": "65950121000140",
        "label": "Chave copia e cola"
    },
    {
        "kind": "text",
        "content": "Caso ache mais fácil, aqui em cima você pode apenas clicar em \"Copiar chave Pix\", e colar lá no banco 🩵",
        "label": "Instrução de cópia"
    },
    {
        "kind": "text",
        "content": "Fico no aguardo do comprovante🥰❤️",
        "label": "Aguardo"
    },
    {
        "kind": "text",
        "content": "🎁 BÔNUS EXCLUSIVOS APÓS SEU PAGAMENTO\n\nE não acaba por aqui… 🤩🙏\n\nAssim que você enviar o comprovante, eu libero pra você:\n\n🎁 Acesso à nossa Comunidade de Famílias na Palavra\n(com materiais e conteúdos exclusivos)\n\n🎁 Acesso às novidades semanais nos Status\n(não esquece de salvar meu contato 💛)\n\n🎁 Materiais extras para aplicar com as crianças no dia a dia\n\n✨ Tudo isso totalmente gratuito pra você",
        "label": "Bônus"
    },
    {
        "kind": "text",
        "content": "💛 Assim que fizer o pagamento, me envia o comprovante aqui que eu já libero tudo pra você 🙏",
        "label": "Pedido de comprovante 1"
    },
    {
        "kind": "text",
        "content": "Quando pagar, por gentileza, manda o comprovante aqui na nossa conversa!!\n\nPode ser um Print também, apenas para me ajudar com o controle do financeiro ❤️",
        "label": "Pedido de comprovante 2"
    }
]

for card in data["cards"]:
    if card["id"] in ["fechamento_premium", "fechamento_base"]:
        card["tools"] = new_tools

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
