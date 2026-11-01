# Importação de arquivos QGIS / QEPANET

O importador reconhece as extensões `QEPANET-JUNCTIONS`, `QEPANET-RESERVOIRS`,
`QEPANET-TANKS`, `QEPANET-PIPES`, `QEPANET-VERTICES` e `QOPTIONS`, inclusive
depois de `[END]`. Essas seções podem produzir erro 201 no editor EPANET.

O arquivo original fica intacto. A cópia de leitura transporta essas seções como
comentários identificados, que também permitem recuperar os dados ao reimportar
no AVANT HIDRO. Outras seções desconhecidas continuam sujeitas à validação normal.

## Dados aproveitados

- **Material:** aplicado à propriedade da tubulação, conservando o texto recebido.
  `Plastic` continua `Plastic`; esse termo genérico não identifica especificamente PVC.
- **Delta Z:** preservado como informação de origem. A cota hidráulica da seção
  EPANET já inclui esse deslocamento e não é recalculada nem somada novamente.
- **Terreno:** nos nós e tanques, cota hidráulica menos delta Z; nos reservatórios,
  carga total menos delta Z e carga de pressão informada pelo QEPANET.
- **Vértices:** cada cota Z é associada, na ordem de ocorrência por trecho, ao
  vértice XY correspondente. Divergências de quantidade impedem a associação e
  geram aviso; dados inválidos não deslocam as cotas dos vértices seguintes.
- **Descrições e etiquetas:** conservadas nos elementos. Dados originais de
  energia, qualidade, relatório, plano de fundo e opções ficam arquivados no
  histórico de importação do projeto; guardar o texto não ativa sua simulação.
- **Proveniência:** arquivo, SHA-256, unidades, seções auxiliares e avisos são
  registrados no projeto SHCAD, nos dez registros de importação mais recentes.

Selecione um elemento para consultar **Dados de origem — QGIS / EPANET** no painel
de propriedades. Nos trechos com perfil, **Ver cotas dos vértices** abre uma tabela
com coordenadas originais e cotas em metros, que pode ser copiada ou exportada em CSV.
Não se presume um sistema de referência espacial a partir dos valores XY.

O projeto SHCAD preserva os metadados. Na exportação INP, materiais, delta Z e
perfis ainda compatíveis com a geometria são transportados em comentários,
sem criar seções estrangeiras ativas. As unidades hidráulicas de saída são LPS.
Esses comentários auxiliares não alteram o hash do conteúdo hidráulico.

## Dados ainda a definir

O cadastro de uma bomba com `POWER 0` é aceito para edição. O leitor usa um valor
somente na cópia temporária para conseguir criar o objeto, sem executar cálculo;
o modelo devolvido mantém exatamente **0 kW** e a validação bloqueia a simulação
até informar potência ou curva. Nenhuma potência é dimensionada automaticamente.

Tanques sem dimensões, níveis a definir e outros problemas hidráulicos também
são mantidos e sinalizados. A geometria é importada sem conectar nós, fundir
coordenadas próximas ou recalcular os comprimentos informados.

## Referências do formato

- [QEPANET — definição das seções auxiliares](https://github.com/aecforge/QEPANET/blob/master/model/network.py)
- [QEPANET — gravação de cotas e metadados](https://github.com/aecforge/QEPANET/blob/master/model/inp_writer.py)
- [EPANET 2.2 — formato INP](https://usepa.github.io/EPANET2.2/back_matter.html)
