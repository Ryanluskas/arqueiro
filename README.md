# Arqueiro

Automação (RPA) para **simulação de crédito consignado** no portal do parceiro Santander.

Lê uma base de clientes em planilha, executa a simulação para cada um e organiza os
resultados, com interface gráfica para acompanhar a execução.

## Stack
- Python 3
- [Playwright](https://playwright.dev/python/) — automação do navegador
- pandas + openpyxl — leitura/escrita de planilhas
- GUI em `gui.py`

## Instalação
```bash
pip install -r requirements.txt
playwright install
```
Ou use o `instalar.bat` no Windows.

## Uso
```bash
python gui.py
```
Ou rode direto pelo `iniciar.bat`.

## Configuração
As credenciais do portal ficam em `credenciais.ini` (**não versionado**, protegido pelo `.gitignore`).
As bases de clientes (`.xlsx`/`.csv`) também ficam fora do repositório por conterem dados pessoais.
