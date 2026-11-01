# Validação da atualização AVANT HIDRO 1.2.0

## Resultado

- Identidade atualizada na abertura, título da janela, menus, Sobre, manual, gráficos,
  relatórios HTML/PDF, linha de comando, logs, ícones e metadados do Windows.
- Logo completo fornecido preservado; ícones Windows com nove resoluções.
- Arquivos `.shcad`, protocolos de cálculo e identificadores existentes preservados.
- MIT original preservada integralmente, com crédito `Copyright (c) 2026 caioews` e aviso
  adicional das contribuições. Origem e alterações registradas em `NOTICE.md`.
- Inventário com 32 dependências e 79 textos originais de licença; textos GNU e avisos
  de Python também acompanham o pacote. As licenças de bibliotecas não foram trocadas por MIT.
- Empacotamento concluído com PyInstaller 6.22.3; versão de produto e arquivo 1.2.0,
  produto AVANT HIDRO e copyright original presentes nos metadados do executável.
- Fontes correspondentes da aplicação incluídos em `AvantHidro-fontes.zip`.

## Verificações executadas

- **282 testes aprovados, 5 ignorados, 9 advertências existentes**, código de saída 0,
  em 77,00 s. Incluem simulação/otimização, gráficos, renumeração, troca de elementos,
  persistência e interface.
- **11 testes de marca/ajuda/abertura aprovados**, código de saída 0.
- `python -m pip check`: sem requisitos quebrados.
- Conferência visual da abertura, Sobre, MIT, manual e relatório com logo incorporado.
- Simulação adicional de rede de exemplo pelo código-fonte: status `ok`.
- Verificação de licença original por comparação integral com a cópia preservada.
- Verificação de ícones pequenos e de alta resolução e transparência do recurso mestre.

## Limitação do teste do executável

O executável foi gerado, mas o Windows impediu sua execução neste computador com
**WinError 4551: uma política de Controle de Aplicativo bloqueou este arquivo**.
Por isso, os testes de versão/CLI/cálculos pelo `.exe` não puderam ser concluídos.
A política de segurança não foi alterada. A validação funcional foi feita pelo
código-fonte, executado com o Python do ambiente virtual do projeto.

Para executar pelo terminal do VS Code, na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Distribuição local

Pasta: `C:\APP_AVANT\AVANT_HIDRO_1.2.0\AvantHidro`.

As cópias anteriores dos arquivos alterados estão em
`C:\APP_AVANT\hidropy-before-avant-branding`. Os logs de testes, compilação e
prévias ficam em `C:\APP_AVANT\avant-hidro-branding-preview`.
Não houve commit, push nem alteração da URL do repositório.
