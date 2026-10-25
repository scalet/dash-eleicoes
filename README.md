# Apuração Presidente 2026 · 2º turno

Página local para acompanhar a apuração oficial do segundo turno da eleição presidencial de 2026. Os números vêm dos arquivos do TSE. Ao lado, um feed do X (imprensa e políticos): ao vivo, se houver token, ou o recorte real que vem no repositório.

Não é um site do TSE.

## Requisitos

Python 3.9 ou mais novo. Não precisa de `pip` — só a biblioteca padrão.

## Como rodar

```bash
git clone https://github.com/scalet/dash-eleicoes.git
cd dash-eleicoes
python3 server.py
```

Abra http://localhost:8765

No Windows: `python server.py`

O servidor consulta o TSE a cada 60 segundos. A página pede os números a cada 30 segundos. Na primeira execução, se `posts.json` não existir, ele é copiado de `posts.sample.json`.

Outra porta: `python3 server.py --port 9000` ou `PORT=9000 python3 server.py`. No PowerShell: `$env:PORT=9000; python server.py`

Para testar só o arquivo nacional do TSE: `python3 fetch.py`

## Feed do X (opcional)

Sem `X_BEARER_TOKEN`, o feed mostra o recorte salvo e a página avisa: `feed do X desativado — defina X_BEARER_TOKEN`. O servidor não inventa posts.

```bash
export X_BEARER_TOKEN="cole-o-token-aqui"
python3 server.py
```

A cada 5 minutos ele consulta `https://api.x.com/2/tweets/search/recent` com as buscas de `POSTS_QUERIES.md` (`expansions=author_id`, `user.fields=name,username`, `tweet.fields=created_at,public_metrics`) e grava `posts.json`. No PowerShell: `$env:X_BEARER_TOKEN="cole-o-token-aqui"; python server.py`

Não commite o token. `posts.json` e `last_data.json` ficam de fora do git.

## Fonte dos dados

Eleição 6258:

- Brasil: https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json
- Estado: `https://resultados.tse.jus.br/oficial/ele2026/6258/dados/<uf>/<uf>-c0001-e006258-u.json`

`<uf>` é a sigla em minúsculas. `zz` é o Exterior.

## Se algo der errado

- **Porta em uso.** O terminal avisa. Use `python3 server.py --port 8766`.
- **TSE sem parcial nova.** Se o horário publicado não mudar por 10 minutos, a faixa amarela diz “Sem novas parciais”. A apuração oficial às vezes pausa; a página continua consultando.
- **TSE fora ou sem rede.** Vale o último `last_data.json`. Na primeira vez, sem cache, espere o ciclo de 60s e olhe o terminal.
- **Feed do X parado.** Sem token, é o recorte de exemplo. Com token, o erro da API aparece no terminal e os posts já salvos continuam na página.
- **Página em branco.** Abra `http://localhost:8765`. Abrir o `index.html` direto no disco não funciona.

## Arquivos

| Arquivo | Função |
|---|---|
| `server.py` | Sobe o site, consulta o TSE e, com token, o X |
| `fetch.py` | Baixa e interpreta os JSON do TSE |
| `merge_posts.py` | Junta e ordena os posts |
| `index.html` | A página |
| `geo/map.json` | Contorno dos estados |
| `posts.sample.json` | Recorte real de posts |
| `POSTS_QUERIES.md` | Consultas do feed |
