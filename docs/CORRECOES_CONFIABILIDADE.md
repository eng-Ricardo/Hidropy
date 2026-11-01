# Correções de confiabilidade hidráulica

## Comportamento

- A otimização não reduz automaticamente a pressão mínima por topografia. O alvo de
  atendimento é `max(pressao_min, pressao_min_absoluta)`, com a tolerância configurada.
- `perda_admitida_excecao` permanece nos projetos antigos para compatibilidade de leitura,
  mas não relaxa as restrições. A interface não oferece mais esse parâmetro.
- A seleção do algoritmo genético compara primeiro a violação total e depois o custo.
  Portanto, qualquer candidato viável precede qualquer candidato inviável. Quando não há
  solução viável, o resultado continua disponível como diagnóstico, explicitamente inviável.
- Tubos fixos não mudam de diâmetro e não entram no custo de implantação. Todos os tubos
  participam das verificações de velocidade e, quando ativada, perda unitária.
- A simulação e o otimizador usam uma verificação comum de convergência, relatório EPANET,
  cobertura dos instantes esperados, elementos e resultados numéricos finitos.
- O timeout da CLI/adaptadores cobre a leitura dos logs e a espera do processo. O processo
  é encerrado e aguardado ao exceder o prazo ou ocorrer erro no consumidor de logs.

## INP e projetos existentes

A importação/exportação preserva modelo DDA/PDA, pressões e expoente PDA, viscosidade,
gravidade específica, expoente dos emissores, parâmetros de convergência, deslocamento dos
padrões e início do relatório. A exportação mantém segundos nos tempos.

Os controles simples são normalizados pelo WNTR para unidades métricas antes de serem
incorporados ao projeto. Isso preserva pressão, nível e ajustes numéricos de válvulas.

Dados de qualidade da água, energia, regras e estatísticas agregadas de relatório ainda
não são representados integralmente pelo modelo interno. A importação informa o descarte
ou a substituição desses dados. O relatório hidráulico usa séries temporais completas.

Projetos `.shcad` antigos continuam abrindo; os novos campos recebem valores padrão quando
ausentes. Os novos parâmetros fazem parte da exportação usada no hash: resultados antigos
devem ser recalculados para serem considerados atuais. Soluções anteriormente aceitas por
pressão relaxada ou por omissão dos trechos fixos podem agora ser classificadas como inviáveis.

## Rastreabilidade e validação

Resultados novos registram versões de Python/WNTR/NumPy, versão EPANET, opções hidráulicas
e temporais. Otimizações registram também configuração, semente e políticas de seleção e
pressão. O hash do INP e o hash do script continuam sendo registrados.

`tests/test_hydraulic_regressions.py` cobre os casos de pressão baixa, preferência por
viabilidade, menor violação, tubos fixos, convergência, timeout, preservação PDA e controles
em unidades LPS/GPM/CMH, usando o motor real sempre que necessário.

`requirements-windows-py312.lock` registra o ambiente Windows/Python 3.12 validado.
O workflow de GitHub Actions foi preparado para executar a suíte; ele será executado no
GitHub quando as mudanças forem enviadas. O executável distribuído precisa ser reconstruído
com `AvantHidro.spec` para incorporar as correções do código-fonte.
