# Recursos da marca AVANT HIDRO

## Arquivos finais

- `src/resources/avant_hidro_logo.png`: logo completo fornecido pelo usuário, copiado sem alteração de pixels.
- `src/resources/avant_hidro_icon_master.png`: gota isolada com transparência, produzida pelo modo embutido da habilidade `imagegen` a partir do logo fornecido.
- `src/resources/avant_hidro_256.png`: versão de 256 px para uso como ícone.
- `src/resources/avant_hidro.ico`: contêiner Windows com tamanhos 16, 20, 24, 32, 40, 48, 64, 128 e 256 px.
- `docs/img/interface.png`: captura atualizada do programa, produzida a partir da interface real com uma rede de exemplo.

O logo completo aparece na abertura, no Sobre, no manual e nos relatórios.
O símbolo da gota identifica a janela e o executável. As exportações PNG/ICO foram
feitas de forma determinística a partir do recurso mestre para os formatos do Windows.

## Prompt utilizado no modo embutido de imagegen

```text
Edit target: the attached AVANT HIDRO logo. Produce ONLY the blue water droplet symbol from the upper-right of the supplied logo as a square application icon asset on a genuinely transparent background. Preserve its exact characteristic outline, blue/cyan gradient and interior flowing blue wave shapes. Center the complete isolated droplet large in the square with a small clear margin so it reads at small icon sizes. Remove all lettering, tagline, orange swoosh and black backdrop. Do not redesign, do not add any text, badge, new motifs, shadows, or backgrounds. This is a faithful extraction of the existing brand mark for Windows taskbar/application icons.
```

O recurso gerado foi conferido e integrado ao projeto; a imagem completa enviada
pelo usuário continua sendo a referência visual principal.
