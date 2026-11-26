---
name: txtest
description: Crie, calibre e execute rubricas .txtest e aplique suas instruções de autoria ao escrever ou revisar o material que será testado. Inclui leituras condicionais por linguagem.
---

# txtest

Na raiz do projeto que contém `txtests/`, rode `txtest ARQUIVO --set NOME`. A CLI lê o arquivo UTF-8 e executa cada `.txtest` de `txtests/NOME/` em ordem de nome. Jev é o provedor padrão; use `--provider decisions` para selecionar a Decisions API. Configure a chave no ambiente ou no `.env`: `TYPESAFE_API_KEY` para Jev e `OPENAI_API_KEY` para Decisions. Para as aulas Neps, use `--set lessons --provider jev`.

## Revise a apresentação, preserve o que a aula ensina

Ao revisar uma aula com o txtest, use a falha para investigar **como a explicação chega ao aluno**. Uma informação correta pode estar mal apresentada. A pergunta é: “Como posso explicar essa mesma ideia a partir do que o aluno já sabe ou acabou de observar?” Reescreva a passagem preservando o que ela ensina, seus exemplos e as condições em que valem. Releia-a com os parágrafos vizinhos antes de testar a aula inteira. Uma nota maior não compensa uma explicação mais pobre.

Na aula sobre condições, o programa aceitou um pedido de 9 peças que deveria recusar. Partir da diferença entre a saída esperada e a observada deu sentido à comparação com erros que aparecem mais cedo: o parêntese sem fechar e a divisão por zero. Os três exemplos ficaram na aula. Retirar um trecho de uma cópia pode ajudar a localizar o sinal do teste; isso não indica que o trecho deva sair da aula.

## Oriente quem escreve com `instruct`

Antes de criar ou revisar um texto que será testado, leia o campo `instruct` de cada rubrica aplicável do conjunto e siga as instruções presentes desde a primeira versão. Se delegar a redação ou a revisão, repasse essas instruções a quem fará o trabalho.

Ao criar ou atualizar um `.txtest`, você pode incluir `instruct` como texto no frontmatter YAML. O campo é opcional: use-o quando houver uma orientação concreta para quem escreve. A CLI não envia esse campo aos avaliadores. Por exemplo, “Priorize frases mais longas” pertence a `instruct`; a pergunta “Os pontos interrompem uma mesma explicação?” pertence a `<system>`.

## Escreva a pergunta que o avaliador precisa decidir

Escolha **uma característica que se reconhece em uma leitura rápida**. Diga, em português nas rubricas das aulas, onde olhar e o que distingue os casos. “O parágrafo é bom?” delega ao modelo a definição do critério. Para fluidez, por exemplo, pergunte se pontos sucessivos separam em pequenas afirmações partes de uma mesma explicação. Não peça uma contagem que um script pode fazer, nem uma simulação mental de todo o programa. Peça um julgamento, não uma correção.

Use um exemplo breve e, de preferência, real. Um par com os mesmos fatos ensina mais que uma lista de adjetivos. Para explicação direta, “esses tempos não medem sua facilidade com programação” é uma ressalva quando o aluno só quer planejar a semana; é uma resposta pertinente quando ele perguntou se demorar mais indica dificuldade. O que muda é o contexto, não a presença da palavra “não”. Explique esse contraste em uma frase. Deixe fora do prompt a discussão interna que levou à regra.

Em `txtests/<conjunto>/<nome>.txtest`, use uma `description` curta para a tabela, `<system>` para o critério e `<user>` para o texto. Ambos aceitam Jinja com `text`, `filename` e `path`. Para um predicado, alinhe a pergunta e a resposta: **SIM significa que o critério foi atendido**. Se uma ocorrência clara deve reprovar a aula inteira, diga isso; não peça uma avaliação média. Uma pergunta sobre a *presença do defeito* inverte o sentido do SIM: não a adote como teste de aprovação sem confirmar suporte à inversão.

```text
---
description: Informa até quando e por qual canal pedir reembolso.
type: predicate
min_probability: 0.6
---
<system>
O texto informa tanto o prazo quanto o canal para pedir reembolso?
</system>
<user>
{{ text }}
</user>
```

Em `predicate`, o corte é `min_probability` (padrão: 0.5). Para `score`, defina cinco `levels` ordenados, cada um com `label` diferente e `description` concreta; `min_score` tem padrão 4 na escala de 1 a 5.

## Calibre antes de adotar

1. Escolha de antemão um trecho que deve passar, uma cópia que deve falhar por **uma única mudança** e um caso parecido que merece passar. Guarde um exemplo de outro assunto fora do prompt para a confirmação. Meça a rubrica atual antes de modificá-la.
2. Teste a candidata nos trechos, mantendo provedor e corte fixos. Mude uma coisa por rodada: a pergunta, o contraste ou a instrução de decisão. Observe tanto os defeitos que passam quanto os cuidados úteis que falham. Aumentar o rigor às custas destes últimos não melhora a separação.
3. Faça o teste decisivo em duas **cópias da aula inteira**, uma com e outra sem a ocorrência. Não indique o parágrafo ao avaliador. Confira cada percurso visível e outra aula que não serviu de exemplo. Um bom resultado isolado não garante que o modelo encontre uma frase no meio de uma aula.
4. Prefira a formulação que põe bons e maus casos em lados opostos do corte **com margem**. Se estiverem perto do limite, repita o mesmo par sem mudanças e registre a variação. Só depois considere ajustar o corte com base no conjunto de casos, nunca para aprovar uma aula específica. Guarde a versão testada, os pares e as limitações que restaram.

Faça experimentos em cópias e conjuntos separados do conjunto em uso. Para isolar um critério, use um conjunto temporário que contenha só a rubrica desejada; `--block` seleciona conteúdo, não critérios.

## Execute e interprete

```bash
txtest aula.md --set lessons --provider jev --block language:c
txtest aula.md --set lessons --provider jev --block language:python
```

Use os valores presentes nos marcadores `[TIPO VALOR]` e `[endTIPO]` do arquivo (por exemplo, `--block language:cpp` para C++). Cada execução avalia o texto comum mais os blocos selecionados. Repetir `--block` na mesma chamada mantém os valores selecionados juntos; faça chamadas separadas para leituras independentes. Sem a opção, a CLI avalia o arquivo inteiro.

A CLI retorna `0` se todos os testes passaram, `1` se houve reprovação sem erro de execução e `2` em caso de erro. Leia as linhas do relatório: **Passou**, **Falhou** e **Erro de execução** são resultados distintos. Uma porcentagem de predicado é uma estimativa do julgamento do modelo, não a porcentagem de parágrafos corretos. A nota se refere ao texto enviado: não localiza o trecho nem demonstra a causa de uma variação. Cabe ao agente ler a passagem, avaliar o efeito no aluno e decidir se a aula ou a rubrica precisa mudar.
