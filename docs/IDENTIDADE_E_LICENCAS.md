# AVANT HIDRO 1.2.0 — identidade e distribuição

A marca pública é AVANT HIDRO, com o subtítulo **Modelagem e projeto de redes hidráulicas**.
O arquivo `src/branding.py` centraliza nomes, caminhos de recursos e identidade no Windows.
O logo completo fornecido permanece em `src/resources/avant_hidro_logo.png`; o símbolo
da gota é usado no ícone com tamanhos de 16 a 256 pixels.

O formato `.shcad`, os identificadores persistentes e os arquivos INP anteriores
continuam compatíveis. O nome interno do diretório Git e a URL do repositório
continuam os mesmos. Logs novos ficam em `%LOCALAPPDATA%/AvantHidro/logs/avant-hidro.log`.

## Origem e licença

O aviso original `Copyright (c) 2026 caioews` e todo o texto MIT estão preservados em
`LICENSE`. A atribuição ao HidroPy e ao autor original também aparece na abertura,
na janela Sobre, no manual, no README e no `NOTICE.md`.

A MIT cobre o código da aplicação e suas alterações. Bibliotecas e fontes mantêm
suas próprias licenças, copiadas sem alteração para `licenses/`. A tela
**Ajuda → Sobre o AVANT HIDRO → Licenças e atribuições** apresenta os textos e o inventário.

Referências: [MIT — OSI](https://opensource.org/license/mit),
[Qt — condições de uso LGPL](https://www.qt.io/development/open-source-lgpl-obligations).

## Empacotar no Windows

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python tools/collect_licenses.py
python tools/build_windows.py
```

Distribua a pasta inteira `dist/AvantHidro`, com as bibliotecas dinâmicas,
textos de licença, atribuições e código-fonte correspondente da aplicação.
O arquivo `HidroPy.spec` continua como entrada compatível para o novo empacotamento.
O compilador usa um PATH temporário isolado, limpa o cache e executa automaticamente
`AvantHidro.exe --diagnostico` antes de aprovar o pacote. Esse teste carrega QtWidgets,
os recursos de marca e a janela principal, sem abrir um projeto do usuário.
O resultado fica em `verificacao-executavel.json`; detalhes de falhas ficam em
`build/diagnostico-executavel.log`. O pacote Windows 10/11 utiliza a ICU nativa do
Windows e não inclui uma `icuuc.dll` incompatível de ferramentas externas.
Um bloqueio por Controle de Aplicativo é registrado como `blocked`; o comando termina
com erro e não aprova a compilação. Licenças e fontes ainda acompanham o artefato gerado.
Antes de distribuir binários com versões diferentes de dependências, regenere
o inventário e confira as obrigações das respectivas licenças, inclusive fontes
correspondentes das bibliotecas LGPL usadas na distribuição.
