# Editores de curvas e padrões

As janelas de Rede hidráulica → Curvas e Padrões temporais foram reorganizadas
com identificação, descrição, tabela de dados e prévia gráfica, tomando os
editores do EPANET 2.2 como referência.

## Edição e aplicação

- A lista à esquerda reúne os objetos. **Novo**, **Duplicar** e **Excluir** são
  alterações locais até clicar em **Aplicar** ou **OK**.
- Trocar de item na lista conserva inclusive células ainda incompletas. Um
  asterisco indica alterações pendentes.
- **Aplicar** grava todas as alterações pendentes em uma operação de desfazer.
  **OK** aplica e fecha. **Cancelar** descarta somente o que ainda não foi aplicado.
- Nomes e descrições podem ser editados sem mudar o UID e as associações existentes.
  IDs devem ser únicos na categoria e conter até 31 caracteres sem espaços.
- O editor rejeita dados alterados externamente ou mudança de cenário durante a edição.

## Curvas

As unidades internas são L/s, m, m³ e porcentagem. A prévia muda ao confirmar
células e mostra os pontos e a curva resultante.

- **Bomba:** vazão × carga, com carga decrescente. Um ponto, ou três pontos
  começando em vazão zero, produzem o ajuste `H = A − B Q^C`, com `0 < C ≤ 20`,
  cuja equação é mostrada. Os demais casos usam interpolação linear por trechos.
  Isso inclui três pontos cuja primeira vazão é positiva, conforme o motor EPANET.
- **Rendimento:** vazão × eficiência, entre 0 e 100%.
- **Volume:** nível × volume, ambos estritamente crescentes.
- **Perda de carga (GPV):** vazão × perda, com ao menos dois pontos.

Uma curva associada a bomba, tanque ou GPV deve continuar do tipo necessário ao
elemento. Duplique a curva para produzir dados de outro tipo.

## Padrões

A tabela horizontal mostra cada período, seu intervalo e o multiplicador. O
gráfico mostra o ciclo completo, a média, mínimos/máximos e a posição em `t=0`
quando o início global do padrão define um deslocamento.

Passo e início permanecem globais, nas opções de simulação. Não são alterados
pela edição dos multiplicadores. **Média = 1** é uma operação explícita que divide
os valores pela média positiva; o editor não normaliza dados automaticamente.
Multiplicadores negativos são aceitos como no EPANET e destacados na prévia.

O padrão global não pode ser excluído enquanto estiver selecionado nas opções.
Ao excluir outro padrão, suas referências são removidas ao aplicar, e Ctrl+Z
restaura tanto o padrão quanto as referências.

## Planilhas e arquivos

**Copiar/Colar** e Ctrl+C/Ctrl+V transferem dados da tabela. Vírgula decimal é
aceita. Curvas usam duas colunas; padrões aceitam uma linha/coluna de fatores ou
colunas Período/Multiplicador.

**Carregar** e **Salvar arquivo** suportam PAT/CRV do EPANET e CSV com cabeçalhos.
O formato nativo guarda a descrição em uma linha e os valores nas unidades da
janela. CSV guarda os valores e cabeçalhos. Cabeçalhos opcionais são reconhecidos,
mas linhas numéricas inválidas causam erro com indicação da linha, sem descarte silencioso.
Os dados carregados continuam pendentes até aplicar. Salvar um arquivo não aplica
automaticamente as alterações ao projeto.

As descrições também são preservadas na exportação/importação INP e no projeto SHCAD.

## Referências de comportamento

- [EPANET 2.2 — editores de objetos](https://github.com/USEPA/EPANET2.2/blob/master/User_Manual/docs/6_objects.rst)
- [EPANET 2.2 — curvas e padrões](https://github.com/USEPA/EPANET2.2/blob/master/User_Manual/docs/3_network_model.rst)
- [Formato CRV no editor oficial](https://github.com/USEPA/EPANET2.2/blob/master/Delphi_GUI/epanet2w/Dcurve.pas)
- [Formato PAT no editor oficial](https://github.com/USEPA/EPANET2.2/blob/master/Delphi_GUI/epanet2w/Dpattern.pas)
- [Regra de ajuste no motor EPANET](https://github.com/USEPA/EPANET2.2/blob/master/SRC_engines/src/solver/input2.c)
