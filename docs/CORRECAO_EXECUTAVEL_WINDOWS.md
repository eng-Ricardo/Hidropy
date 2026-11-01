# Correção do executável Windows — AVANT HIDRO 1.2.0

## Causa confirmada

A importação de `PySide6.QtWidgets` no executável falhava com
`DLL load failed ... Não foi possível encontrar o procedimento especificado`.

As DLLs do Qt e do Python correspondiam às do ambiente de origem. O rastreamento
das dependências revelou uma `icuuc.dll` externa, obtida de uma ferramenta no PATH
do processo de compilação. Essa DLL exportava a ABI ICU 78 e não fornecia 20 símbolos
sem sufixo exigidos pelo Qt6Core, como `ucnv_open` e `ucnv_close`.
Na execução que funcionava pelo Python, essas funções eram fornecidas pela ICU do Windows.

O erro foi reproduzido pelo executável de diagnóstico. Ao retirar as duas DLLs ICU
externas apenas da cópia de teste, a interface passou a carregar e renderizar,
com `icuuc.dll` e `icu.dll` provenientes de `%WINDIR%/System32`.

## Correção aplicada

- O compilador usa PATH temporário limitado ao ambiente Python e ao Windows.
- O cache do PyInstaller é limpo em cada compilação.
- A especificação exclui cópias globais de ICU que poderiam ocultar a biblioteca
  nativa no Windows 10/11; bibliotecas versionadas e internas de pacotes são mantidas.
- O novo comando `--diagnostico` carrega QtWidgets, recursos e a janela principal,
  renderiza a interface e informa falhas em JSON.
- O script de compilação testa o próprio executável antes de aprovar a distribuição.
  Um erro de DLL, falha nativa ou bloqueio do Windows reprova a validação.

Nenhuma biblioteca do Windows, instalação Python ou política de segurança foi alterada.

## Recompilar

Na pasta `C:\AVANT\SOFTWARES\Hidropy`:

```powershell
.\.venv\Scripts\python.exe tools\build_windows.py
```

Saída: `dist/AvantHidro/AvantHidro.exe`. Distribua a pasta `AvantHidro` inteira.
O resultado do teste nativo fica em `verificacao-executavel.json` dentro da pasta.
O log detalhado fica em `build/diagnostico-executavel.log`.

Para rodar o diagnóstico manualmente:

```powershell
.\dist\AvantHidro\AvantHidro.exe --diagnostico
```

## Resultado desta correção

A cópia de diagnóstico, depois de removida a ICU externa, carregou e renderizou
a janela principal com status `ok` e código de saída 0. A suíte completa passou
em 285 testes (5 ignorados). Os testes adicionais do registro de bloqueios e da
aprovação do pacote também passaram.

A nova compilação terminou, mas seu teste de execução foi impedido pelo
Controle de Aplicativo do Windows, WinError 4551. O artefato final está marcado
como `blocked`, não como aprovado. Isso é distinto da incompatibilidade de ICU
reproduzida e corrigida. A política de segurança não foi alterada.
