# Consultas do feed do X

O `server.py` lê este arquivo quando a variável `X_BEARER_TOKEN` está definida.
A cada 5 minutos ele acrescenta `since:` com cerca de 30 minutos atrás (UTC) e
chama:

`GET https://api.x.com/2/tweets/search/recent`

Parâmetros fixos: `max_results=25`, `expansions=author_id`,
`user.fields=name,username`, `tweet.fields=created_at,public_metrics`.

Não inclua `since:` na linha — o servidor coloca. Uma linha de consulta começa
com `(`. O título da seção (`## imprensa` ou `## politicos`) é a categoria.
As duas buscas de políticos entram na mesma categoria.

O resultado passa por `merge_posts.py`: ignora respostas (texto começando com
@), atualiza métricas de posts já vistos, limita 4 por autor e guarda os 20
melhores de cada categoria (recência + engajamento). Sem token, o servidor não
chama o X e não inventa posts: a página mostra `posts.sample.json`.

Dá para mesclar um dump manual (o nome do arquivo define a categoria:
`imprensa…` ou `politicos…`):

```bash
python3 merge_posts.py raw/imprensa.json raw/politicos.json
```

## imprensa

(from:g1 OR from:folha OR from:Estadao OR from:CNNBrasil OR from:JornalOGlobo OR from:UOLNoticias OR from:BandJornalismo OR from:metropoles OR from:TSEjusbr OR from:GloboNews) -is:retweet -is:reply

## politicos

(from:LulaOficial OR from:FlavioBolsonaro OR from:jairbolsonaro OR from:gleisi OR from:tarcisiogdf OR from:padilhando OR from:Haddad_Fernando OR from:nikolas_dm OR from:geraldoalckmin) -is:retweet -is:reply

## politicos

(from:GuilhermeBoulos OR from:CarlosBolsonaro OR from:BolsonaroSP OR from:romeuzema) -is:retweet -is:reply
