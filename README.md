# ⚽ Football Predictor

Site estático com previsões simples das **5 grandes ligas europeias**:

- Premier League  
- La Liga  
- Serie A  
- Bundesliga  
- Ligue 1  

**Modelo (v2):** Poisson com força de ataque e defesa por equipa, estimada com a época atual + a anterior (jogos recentes pesam mais), encolhida para a média da liga com poucos jogos, mando de campo estimado dos dados, correção Dixon-Coles para placares baixos e golos esperados limitados a um intervalo realista. Detalhes em `scripts/model.py`.

**Resultado mais provável:** destaca a opção com maior probabilidade (Casa / Empate / Fora). Não é uma recomendação de aposta, porque sem odds não há como saber se existe valor.

**Confiança (alta / média / baixa):** combina a diferença entre as duas opções mais prováveis com a quantidade de jogos recentes das duas equipas. Com poucos dados fica sempre "baixa".

**Qualidade dos dados:** o site avisa quando o último resultado da fonte é antigo, quando há jogos passados sem resultado, e esconde jogos que já terminaram. A época é detetada automaticamente pela data.

**Dados:** [openfootball/football.json](https://github.com/openfootball/football.json) (domínio público, sem API key).

---

## Como usar (GitHub Pages)

### 1. Crie o repositório

1. Crie um repositório novo no GitHub (ex: `football-predictor`)
2. Faça upload de todos os arquivos desta pasta **ou** clone e faça push:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/football-predictor.git
git push -u origin main
```

### 2. Ative o GitHub Pages

1. Vá em **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / pasta `/ (root)`
4. Save

O site ficará em:  
`https://SEU_USUARIO.github.io/football-predictor/`

### 3. Atualização automática

O workflow `.github/workflows/update-data.yml` roda **a cada 6 horas** e também pode ser disparado manualmente:

1. Aba **Actions**
2. Escolha **Update Football Data**
3. **Run workflow**

**Importante:** o `data/matches.json` incluído no zip é *provisório* (gerado de uma amostra pequena). Rode o workflow manualmente uma vez para carregar a época completa.

---

## Rodar localmente

```bash
# Gera/atualiza os dados
python scripts/update_data.py

# Mede se o modelo presta (walk-forward: Brier, log-loss, calibração)
python scripts/backtest.py

# Serve o site (qualquer servidor estático)
# Exemplo com Python:
python -m http.server 8000
# Abra http://localhost:8000
```

---

## Estrutura

```
├── index.html
├── css/style.css
├── js/app.js
├── data/matches.json          ← gerado pelo script
├── scripts/model.py           ← modelo de previsão
├── scripts/update_data.py     ← descarrega dados e gera previsões
├── scripts/backtest.py        ← avalia o modelo com jogos passados
└── .github/workflows/update-data.yml
```

---

## Aviso

Este é um protótipo estatístico educativo.  
Não constitui aconselhamento de apostas. Futebol tem alta variância.
