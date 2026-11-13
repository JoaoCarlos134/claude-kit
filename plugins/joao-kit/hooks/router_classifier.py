"""Label a prompt chore / standard / deep, or stay silent, from the user's own words. Offline, stdlib.

How the score works (`python model_router.py explain "<prompt>"` prints it for any prompt):

1. Only the user's own words are judged. Pasted blocks (also nested or unclosed ones), fenced code and
   log or traceback lines are cut out first, so "error" and "failed" in a pasted log don't count.
2. Each vocabulary pattern that matches adds its weight once to its tier:
   - chore: mechanical verbs and objects (rename, translate, typo, reformat, to csv, bump ...);
   - standard: action verbs (implement, fix, add, write a script ...), problem reports (bug, crash) and,
     for at most 1 point in total, nouns that only say "this is about code" (function, endpoint ...);
   - deep: `strong` phrases that are enough alone (root cause, trade-offs, data leakage), `intent` verbs
     (analyse, evaluate, design, plan, decide, justify), `depth` words (in depth, profundamente,
     rigorously), `decision` cues (should we, vale a pena, is it valid) and `topic` nouns (methodology,
     security, hypothesis, cost, thesis).
3. A topic noun says where the work happens, not what it is: "fix the typo in the methodology section"
   is a chore. So topics count only when the prompt also asks for thinking (a strong, intent, depth or
   decision match) or names no chore and no action verb at all.
4. Structure (the `structural` switch; off = keywords only, kept for the comparison lab):
   - lead: the job is usually named in the first words, so a chore pattern, a specific action verb or an
     intent verb that starts within LEAD_CHARS of the start adds LEAD_BONUS to its tier;
   - a prompt that already has deep evidence (>= 1) gets up to STRUCTURE_CAP more for being long,
     asking two or more questions, or having three or more parts;
   - two words are enough to judge when something is attached ("summarize this" + a paste).
5. Verdict: questions ("what is", "o que e", anything ending in "?" that isn't a polite request) are
   answered in place and get a label only when they are deep with two separate deep matches or 15+
   words; definitions and thanks never get one. Otherwise deep needs 2 points and at least as many as
   chore and standard; chore needs more points than standard and at most CHORE_MAX_WORDS words;
   standard needs 1 point, more than chore, and something besides nouns. Anything else is silence.

Typos: a word of 7+ letters one edit away from a key word (adcionar, implemnt, profundamnete) is read
as that word.
"""

import re
import unicodedata

CHORE_MAX_WORDS = 80
MIN_WORDS = 3
LEAD_CHARS = 20
LEAD_BONUS = 1.0
STRUCTURE_CAP = 1.5
DEEP_MIN = 2.0

# Every pattern runs on lower-case text without accents. (regex, weight[, "lead"]): "lead" marks the
# patterns that earn LEAD_BONUS when they open the prompt.
CHORE = [(p, 2, "lead") for p in [
    r"\brenam(e|es|ed|ing)\b", r"\brenome\w*", r"\brenombr\w+", r"\brenomm\w+", r"\btypos?\b",
    r"\bspelling\b", r"\bortogra\w+", r"\berros? de digitacao\b", r"\bre-?format\w*", r"\bindent\w*",
    r"\btranslat\w+", r"\btradu[zc]\w*", r"\btradui\w+", r"\balphabeti[sz]e\b",
    r"\b(ordem|orden) alfabetic[ao]\b|\balfabeticamente\b|\balphabetically\b", r"\bbump\b",
    r"\b(upper|lower)case\b", r"\b(snake|camel|kebab|sentence|title)[ _-]?case\b",
    r"\b(change|cambia\w*|mud[ae]\w*|troc[ae]\w*|alter[ae]\w*) (the |el |o )?(name|nombre|nome)\b",
    r"\b(version|versao)\b.{0,50}\b\d+\.\d+(\.\d+)?\b",
    r"\b(turn|make|transform\w*|convert\w*|pass[ae]) .{0,60}\b(into|to|from|em|para|en|a) "
    r"(a |an |um |uma |un |una )?((markdown|numbered|bullet) )?(csv|json|ya?ml|table|tabela|list|lista)\b",
    r"\btabs? (to|para|por|em) (\d+ )?(spaces|espacos)\b",
    r"\bconv[ei]\w+ .{0,40}\b(to|into|para|a|al|em|en) (formato )?(csv|json|ya?ml|markdown|md|xlsx|html)\b",
]] + [(p, 1.5, "lead") for p in [
    r"\b(replace|swap|troque|trocar|troca|substitu\w+) .{0,80}?\b(with|by|por|for)\b",
    r"\b(remove|delete|strip|apague|apaga|remova|tira|tire|exclua|limpe) (the |all |all the |os |as |o |a "
    r"|todos os |todas as )?(unused|trailing|duplicat\w+|empty|blank|comments?|imports?|console\S*|arquivos?"
    r"|linhas?|espacos?|comentarios?|whitespace)",
    r"\borgani[sz]e\w* (the |os |as )?imports?\b",
    r"\b(troc[ae]\w*|cambia\w*) .{0,60}\b(para|pra)\b",
    r"\b(run|roda|rode|ejecuta|corre) (the |o |el )?(formatter|linter|black|isort|prettier)\b",
    r"\b(delete|apaga\w*|remove|borra) .{0,25}\bbranch(es)?\b",
]] + [(p, 1, "lead") for p in [
    r"\bformat(ting|e|ar|a|acao)?\b", r"\bextract\b", r"\bextra(ir|ia|i|e|er)\b",
    r"\bsort\b(?! (it|this|that|things) out)",
    r"\borden(ar|e|a)\b", r"\bsummari[sz]e\b", r"\bresum(a|ir|e|en)\b", r"\blist (all|the|every)\b",
    r"\blist(e|ar)\b", r"\blista (os|as|todos|todas|los|las|cada)\b", r"\bcapitali[sz]\w+", r"\b(em|para|to|in) (maiuscul\w+|minuscul\w+)\b",
    r"\bcommit (this|these|it|that|the|everything)\b", r"\bfa[cz]a (o )?commit\b", r"\bcommit(a|e)\b",
    r"\bgit (status|log|pull|push)\b", r"\bpull request\b",
    r"\bcopy (the |this |these |all )?(files?|folders?|directory)\b", r"\bcopi(ar|e|a)\b",
    r"\bmov(e|a|er) (the |this |these |os |as )?(files?|arquivos?|images?|imagens?)\b",
    r"\b(to|into|para|pra) (csv|json|ya?ml|markdown|md|tabela)\b",
    r"\b(add|update|atualiz\w+|adicion\w+) ((a|an|the|o|os|as) )?([\w-]+ ){0,2}"
    r"(badge|links?|copyright( year)?|status line|linha de status)\b",
    r"\b(add|update|atualiz\w+|adicion\w+) ((a|the|o|today'?s) )?(date|year|data|ano)\b"
    r"(?! (filter|picker|field|column|range|input))",
    r"\bcount (the|how)\b", r"\bconte\b", r"\bquantas vezes\b", r"\bswap\b",
    r"\b(table of contents|indice|sumario)\b", r"\bwrap (the )?lines\b", r"\b(numbered|bullet) list\b",
    r"\bordem cronologica\b|\bchronological(ly)?\b", r"\b(markdown|md) table\b|\btabela markdown\b",
    r"\b(junte|juntar|concatenate|concat) .{0,30}(files?|arquivos?|csvs?)\b", r"\bregenerate\b",
    r"\bpadroniz\w+|\bstandardi[sz]e\b", r"\btidy\b",
]] + [(r"\bregex\b", 0.5)]

# Verbs that name a piece of building work; they earn the lead bonus.
STANDARD_VERBS = [
    # "extract X into a helper" is a refactor, not data extraction: it must outweigh chore "extract"
    (r"\bextract\w* .{0,60}\b(into|to) (a |an )?(helper|function|method|class|module|component)\b", 3, "lead"),
] + [(p, 1, "lead") for p in [
    r"\bimplement(s|ed|ing|e|ar|a)?\b",
    r"\b(write|escrev\w+|escrib\w+) (a |an |the |some |um |uma |un |una |o |os |as )?([\w-]+ ){0,3}"
    r"(script|function|funcao|funcion|tests?|testes?|pytest|query|class|classe|component\w*|workflow"
    r"|helper|endpoint|parser|regex|decorator)\b",
    r"\bcri(ar|e|a) (um|uma|o|a)\b", r"\bcreate (a|an|the)\b", r"\bbuild (a|an|the)\b",
    r"\brefactor\w*", r"\brefator\w*", r"\bdebug\w*", r"\bdepur\w*", r"\bparametri[sz]e\b",
    r"\bhandle (the )?(case|errors?|exceptions?)\b", r"\btrat(e|ar|a) (o |os |a |as )?(caso|erro|excec)",
    r"\bplot (the|a)\b", r"\b(rode|rodar|run|rerun) (o |a |the )?(experiment\w*|training|treino)\b",
]]
# Light verbs and problem reports: the object decides the tier, so no lead bonus.
STANDARD_LIGHT = [(p, 1) for p in [
    r"\bfix(es|ing)?\b", r"\bcorri[gj]\w+", r"\bconsert\w+", r"\barrum(a|e|ar)\b", r"\barregl\w+",
    r"\bupdate (the )?(readme|docs|documentation|roadmap|claude\.md|tests?)\b",
    r"\batualiz\w+ (a |o )?(documentacao|teste|readme)\b", r"\bunit tests?\b",
    r"\bbugs?\b", r"\bcrash\w*", r"\bbroken\b", r"\bquebr\w+", r"\bresolv\w+", r"\bsolve\b",
    r"\b(se cae|cai|caiu)\b", r"\bdoes nothing\b", r"\bnao faz nada\b",
    r"\b(returns?|retorna|devolve) (nan|none|null|nulo|vazio|empty|wrong|errad\w+|500)\b",
    r"\b(doesn'?t|does not|don'?t|won'?t|nao|no) (work|close|open|load|show|funciona|aparece|abre|carrega)\w*",
    r"\b(there'?s|there is|tem|has|found) (a |an |um |uma )(bug|erro|error|problem)",
]] + [(p, 0.5) for p in [
    r"\badd(s|ing)?\b", r"\badicion\w+", r"\bagreg(a|ue|ar)\b", r"\bajout\w+", r"\bmake (the|it|this)\b",
    r"\bmud(a|e|ar)\b", r"\bbota\b", r"\bdocument(a|e|ar)?\b",
    r"\b(write|escrev\w+|escrib\w+|haz|faz|faca|cri[ae]r?|crea|create|build|gera|gere|genera) (me )?"
    r"(a|an|the|um|uma|un|una)\b",
]]
# Reviews, weak symptoms and "it should ..." say something is wanted without naming building work.
STANDARD_WEAK = [(p, 1) for p in [
    r"\breview (this|the|my)\b", r"\brevis(ar|e|ao|a)\b",
]] + [(p, 0.5) for p in [
    r"\bfail(s|ing|ed|ure)?\b", r"\bfalh(a|ando|ou)\b", r"\bfalla\b", r"\berrors?\b",
    r"\berros?\b(?! de digitacao)", r"\btestes?\b", r"\btests?\b",
    r"\b(should|must|needs? to|has to|precisa|deve|tem que)\b",
    r"\b(wrong|errad[oa]s?|incorrect\w*|incorret\w+)\b", r"\boverlap\w*",
]]
STANDARD_NOUNS = [(p, 0.5) for p in [
    r"\bfunctions?\b", r"\bfunc(ao|ion|tion)\b", r"\bfonction\b", r"\bendpoints?\b", r"\bcomponents?\b",
    r"\bcomponente\b", r"\bscripts?\b", r"\bcli\b", r"\bstreamlit\b", r"\breact\b", r"\bmodule\b",
    r"\bmodulo\b", r"\bclass\b", r"\bbutton\b", r"\bbot(ao|on)\b", r"\bbouton\b", r"\bpage\b",
    r"\bpagina\b", r"\bform(ulario)?\b", r"\bfilt(er|ro|re)\b", r"\bcolumns?\b", r"\bcolunas?\b",
    r"\bplot\b", r"\bgrafico\b", r"\bworkflow\b", r"\bflag\b", r"\boption\b", r"\bopcao\b",
    r"\bparamet(er|ro)s?\b", r"\barguments?\b", r"\bcach(e|ing)\b", r"\blogging\b", r"\bspinner\b",
    r"\bprogress bar\b", r"\btoggle\b", r"\bpaginat\w+", r"\bpaginacao\b", r"\bvalida(tion|cao)\b",
    r"\bnotebook\b", r"\bdashboard\b", r"\bhelper\b", r"\bretry\b", r"\bconfig\b", r"\bcampo\b",
    r"\bfield\b", r"\btry/?except\b", r"\bmessage\b", r"\bdropdown\b", r"\bsidebar\b", r"\bchart\b",
    r"\bpicker\b", r"\bdecorator\b", r"\bdocstrings?\b", r"\breadme\b",
]]

DEEP_STRONG = [(p, 2) for p in [
    r"\broot cause\b", r"\bcausa raiz\b", r"\bintermittent\w*", r"\bintermitente\b", r"\bflaky\b",
    r"\brace condition\b", r"\bcondicao de corrida\b", r"\bdeadlock\w*", r"\bmemory leak\b",
    r"\bvazamento de memoria\b", r"\bdata leak\w*", r"\bvazamento de dados\b", r"\btarget leakage\b",
    r"\bfuga de datos\b", r"\bthreat model\w*", r"\bmodelo de ameacas\b", r"\btrade-?offs?\b",
    r"\bpros (and|e|y) con(s|tras?)\b", r"\bsystem design\b",
    r"\bdesign (the|a|an|our|my) (\w+ )?(system|architecture|schema|api|pipeline|data model|database)\b",
    r"\brefactor(ing)? (the whole|across|all|entire|everything|the codebase|the project)\b",
    r"\brefatora\w* (todo|toda|geral|completa)\b", r"\brebuttal\b", r"\bresposta aos revisores\b",
    r"\bsecurity (review|audit|check)\b", r"\b(revisao|auditoria|revision) de segur\w+",
    r"\bonly (happens|fails|occurs) (in|on|when)\b", r"\bnever locally\b", r"\bnon-?determinis\w+",
    r"\bexperiment(al)? design\b", r"\bdesenho (do )?experiment\w*", r"\bdiseno experimental\b",
    r"\bbenchmark design\b", r"\bpass\w* alone\b", r"\bdifferent order each time\b",
    r"\b(once|one run|one time|uma vez|1 vez) (a|per|in|every|a cada|em cada|por|em)\b",
    r"\bone (run|time|request) in\b", r"\blocal(ly)? but\b", r"\bworks? (locally|on my machine)\b",
    r"\bna minha maquina\b",
    r"\b(\d{2,}|dozens of|dezenas de|decenas de) (\w+ )?(files|arquivos|archivos|modules|modulos)\b",
    r"\b(alguem|someone|anyone|attacker|atacante|invasor)\b.{0,30}\b(ler|read|access|acessar|bypass"
    r"|burlar|steal|roubar)\b",
]]
# Verbs that ask for thinking. Those marked "lead" are reliable as an imperative ("analyse ...").
DEEP_INTENT = [(p, 1, "lead") for p in [
    r"\banaly[sz]\w+", r"\banali[sz]\w+", r"\bevalu\w+", r"\bavali\w+", r"\bassess\w*", r"\bcritique\w*",
    r"\binvestig\w+", r"\bdiagnos\w+", r"\bdesign(ing)?\b", r"\bplan (the|a|an|out|how)\b",
    r"\bplanej\w+", r"\bplanif\w+", r"\bprove\b", r"\bprovar\b", r"\bdemonstr[ea]\b", r"\bderiv\w+",
    r"\bwalk me through\b", r"\bnarrow (it )?down\b",
    r"\bdecid\w+", r"\bjustif\w+", r"\binterpret\w+", r"\baudit\b", r"\bestud(ia|ie|e)\b",
    r"\b(figure|find|work) out\b", r"\btrace how\b", r"\breason about\b", r"\bthink through\b",
    r"\breconcil\w+",
]] + [(p, 1) for p in [
    r"\bcompar\w+", r"\brecomm?end\w+", r"\b(um|a|de um|need a) plan[o]?\b", r"\bplano? de\b",
    r"\blook into\b", r"\bgo through\b", r"\bentend(er|a)\b", r"\bpens[ea]\b", r"\bcritic\w+",
    r"\bcheck (whether|if)\b", r"\bverifi\w+ (se|if|whether)\b", r"\b(tell me|me diga|dime) (if|whether|se|si)\b",
    r"\b(what is|o que esta) (missing|faltando)\b", r"\bpontos fracos\b", r"\bweak(nesses| points)\b",
    r"\bcontradi\w+", r"\breasoning\b", r"\braciocinio\b", r"\b(cada passo|each step)\b",
    r"\b(pitfalls|armadilhas|trampas)\b", r"\bpush ?back\b",
    r"\bin (what|which) order\b|\bem que ordem\b|\ben que orden\b",
]] + [(p, 0.5) for p in [
    r"\bestim\w+", r"\bpropo(se|nha|n|r)\w*", r"\bidentif\w+", r"\bantecip\w+", r"\bimpl(y|ies|ica)\b",
    r"\bconclu\w+", r"\b(mas antes|but first|antes de (rodar|implementar)|before (running|implementing))\b",
]]
DEEP_DEPTH = [(p, 1.5) for p in [
    r"\bprofundamente\b", r"\ba fundo\b", r"\baprofundad\w+", r"\bem profundidade\b", r"\bin[- ]depth\b",
    r"\bdeep(ly)?\b(?! learning)", r"\bthorough\w*", r"\brigoros\w+", r"\brigorously\b", r"\bcom rigor\b",
    r"\bcarefully\b", r"\bcom (cuidado|calma)\b", r"\bcuidadosamente\b", r"\ben profondeur\b",
    r"\ba fondo\b",
]] + [(p, 1) for p in [
    r"\bstep by step\b", r"\bpasso a passo\b", r"\bdetalhad\w+", r"\bin detail\b",
]]
DEEP_DECISION = [(p, 1) for p in [
    r"\bshould (we|i)\b", r"\b(devo|devemos|deveria|deveriamos)\b", r"\bvale a pena\b",
    r"\b(is it )?worth\b", r"\bconviene\b", r"\bwhether\b", r"\b(ou|or) (e melhor|is it better|preciso)\b",
    r"\bwhich (one|approach|option|of|hypothes\w+)\b", r"\bqual (das|dos|abordagem|opcao)\b",
    r"\b(should|devo|devemos|deberia\w*) .{0,80}\b(or|ou)\b", r"\b(vale|compensa) mais\b",
    r"\bis (it|this|our|the|my)\b.{0,40}\b(valid|sound|enough|fair|correct|right)\b",
    r"\b(e|sao|son) (o |a )?(suficiente|corret[oa]|valid[oa]|concluyentes|conclusivos)\b",
    r"\b(preciso|necesito|need to|have to) decid\w+",
    r"\bvou (realmente )?precisar\b", r"\b(do|will) i (really )?need\b",
]] + [(p, 0.5) for p in [
    r"\bwhat (would|could|should)\b", r"\bhow (would|could|should)\b", r"\bo que (deve|pode|devo)\b",
    r"\bfaz sentido\b", r"\bmakes? sense\b", r"\bi don'?t know (if|whether|why)\b",
    r"\bnao sei (se|por ?que)\b", r"\bwhat are my options\b",
]]
DEEP_TOPIC = [(p, 1) for p in [
    r"\barchitect\w*", r"\barquitet\w*", r"\barquitect\w*", r"\bmethodolog\w*", r"\bmetodolog\w*",
    r"\bleak(age|s)?\b", r"\bvaza(mento|r)\b", r"\bablation\b", r"\bsecurity\b", r"\bsegur(anca|idad)\b",
    r"\bvulnerab\w*", r"\baudit\w+", r"\bconcurren\w*", r"\bconc[ou]rrencia\b", r"\bstrateg\w*",
    r"\bestrategi\w*", r"\bthesis\b", r"\btes[ei]s?\b", r"\bdissertac\w*", r"\bdissertation\b",
    r"\btcc\b", r"\bmestrado\b", r"\bmigra\w+", r"\bproof\b", r"\bdemonstracao\b", r"\bteorema\b",
    r"\btheorem\b", r"\bstatisti\w+", r"\bestatistic\w*", r"\bestadistic\w*", r"\bsignifica[nt]\w*",
    r"\bhypothes\w*", r"\bhipotes\w*", r"\boverfit\w*", r"\bsobreajuste\b", r"\bp-?val(ue|or)\b",
    r"\bconfidence intervals?\b", r"\bintervalo de confianca\b", r"\bsample size\b", r"\bamostras?\b",
    r"\bsamples\b", r"\bechantillon\b", r"\bcross-?validation\b", r"\bvalidacao (cruzada|temporal)\b",
    r"\bconvergen\w+", r"\bviabilidade\b", r"\bfeasib\w+", r"\bcust(o|os|a|ar)\b", r"\bcosts?\b",
    r"\bcostos?\b", r"\bbill\b", r"\brisks?\b", r"\briscos?\b", r"\briesgos?\b", r"\bbottlenecks?\b",
    r"\bgargalos?\b", r"\bdiverg\w+", r"\bdrift\b", r"\breproduc\w+", r"\bcausal\w*", r"\bcontrato\b",
    r"\bcontract\b", r"\bclausula\b", r"\bclause\b", r"\bidempoten\w+", r"\bargument[o]?\b",
    r"\b(expected|esperad[oa]s?) (results?|resultados?|gain|ganho)\b", r"\bresultados? esperad\w+",
    r"\b(razoavel|what to|o que) esperar\b", r"\bwhole (repo|codebase|project|system)\b",
    r"\bfrom scratch\b", r"\bdo zero\b", r"\bend[- ]to[- ]end\b", r"\brestructur\w+", r"\breestrutur\w+",
    r"\bstandard deviation\b", r"\bdesvio padrao\b", r"\bprobabilit\w+", r"\bprobabilidade\b",
    r"\bhow likely\b", r"\bcorrela\w+", r"\b(control group|grupo de controle)\b",
    r"\b(repeated measures|medidas repetidas)\b",
]] + [(p, 0.5) for p in [
    r"\bbaselines?\b", r"\bpapers?\b", r"\bartigo\b", r"\bexperiment\w*", r"\bscal(e|ing|ability)\b",
    r"\bescal(ar|abilidade)\b", r"\blatenc\w+", r"\bproduc(tion|ao)\b", r"\bvarianc(e|ia)\b",
    r"\bregulariza\w+", r"\binvalida(tion|cao)\b", r"\bassumptions?\b", r"\bpremissas\b",
    r"\breviewers?\b", r"\brevisor(es)?\b", r"\bbanca\b", r"\bclaims?\b", r"\bcontribuicao\b",
    r"\bliteratur[ae]\b", r"\b(maquina virtual|virtual machine|vm|gpu|cloud|nuvem|cluster)\b",
    r"\bapproaches\b", r"\babordagens\b", r"\balternativ\w+", r"\bversus\b", r"\bimpacto?\b", r"\brace\b",
    r"\bregress(ion|ao)\b", r"\btratamentos?\b", r"\btreatments?\b", r"\bshard\w*", r"\bmonolit\w+",
    r"\b(orcamento|budget)\b", r"\bsustenta\w*", r"\bholds? up\b",
]]

GROUPS = (
    ("chore", "chore", CHORE), ("standard", "verb", STANDARD_VERBS), ("standard", "light", STANDARD_LIGHT),
    ("standard", "weak", STANDARD_WEAK), ("standard", "noun", STANDARD_NOUNS),
    ("deep", "strong", DEEP_STRONG), ("deep", "intent", DEEP_INTENT), ("deep", "depth", DEEP_DEPTH),
    ("deep", "decision", DEEP_DECISION), ("deep", "topic", DEEP_TOPIC),
)
COMPILED = [(tier, kind, re.compile(entry[0]), entry[1], len(entry) > 2)
            for tier, kind, table in GROUPS for entry in table]

EVENT_PROMPT = re.compile(
    r"^\s*<(side-sessions-event|ci-monitor-event|task-notification|system-reminder|command-name"
    r"|command-message|command-args|local-command|bash-input|bash-stdout|scheduled-task)")
PASTE_TAG = re.compile(r"<(/?)pasted_content[^>]*>")
FENCE = re.compile(r"```.*?(```|$)", re.S)
# Lines that are machine output, not the user's words. Case matters: people don't open with "ERROR ".
LOG_LINE = re.compile(
    r"^\s*(Traceback \(most recent|File \"|at [\w.$<>]+\(|\d{4}-\d\d-\d\d[ T]\d\d:\d\d|\[?\d\d:\d\d:\d\d"
    r"|\[?(ERROR|WARN|WARNING|INFO|DEBUG|FATAL|CRITICAL|FAILED|PASSED)\b|[\w.]*(Error|Exception|Warning):"
    r"|E   |npm ERR|Caused by:)")
POLITE = re.compile(
    r"^(\W*(please|pls|plz|por favor|pfv|pf|hey|oi|ola|hi|hello|ok|okay|agora|now|then|claude|entao|bom"
    r"|so|and|e)\b[\s,:!]*)*"
    r"((can|could|would|will) (you|u)|(voce |vc )?(pode(ria)?|consegue)|i need you to|i want you to"
    r"|(i|we) (need|want|have) to|i'?d like to|(tb |tambem )?(quero|preciso) que( voce| vc)?"
    r"|help me( to)?|me ajud[ae] a|puedes|peux-tu)?"
    r"[\s,:]*(please|pls|por favor|pfv)?[\s,:]*")
# Opens with a question word ("can you ..." / "pode ..." requests are stripped by POLITE first).
REQUEST = re.compile(
    r"(can|could|would|will) (you|u)\b|(voce |vc )?(pode|poderia|consegue)\b|puedes\b|peux-tu\b")
# A chore verb inside "a script to rename ..." or "que converte ..." describes something, it isn't the ask.
SUBORDINATE = re.compile(
    r"(\b(that|which|que|para|pra)|(?<!need)(?<!want)(?<!like)(?<!have)(?<!going)(?<!able) to) $")
QUESTION = re.compile(
    r"^(what|what's|whats|why|how|where|when|which|who|is|are|does|do|did|was|were|has|have|explain"
    r"|o que|oq|por ?que|pq|como|onde|quando|qual|quais|quant[oa]s?|quem|explique|me expli(que|ca)"
    r"|explica|tem como|da pra|sera que|vc lembra|voce lembra|que|por que|cual|cuanto|donde"
    r"|est-ce que|qu'est-ce|pourquoi|comment)\b")
DEFINITION = re.compile(
    r"^(what(('?s| is| are)) (a|an)\b|what (is|are) the difference|what does\b.{0,60}\bmean"
    r"|o que (e|sao|significa)\b|oq (e|significa)\b|qual (e )?a diferenca"
    r"|(me )?expl(ain|i[qc]\w+)\b.{0,20}\b(what|o que)\b|que es\b|que significa\b"
    r"|qu'est-ce que c'est)")
THANKS = re.compile(r"\b(thanks|thank you|thx|obrigad[oa]|valeu|gracias|merci)\b")

# Key words a typo should still reach; all at least 8 letters, so a one-edit match is rarely a real
# other word.
FUZZY = ("adicionar", "adicione", "implement", "implementar", "implemente", "renomear", "renomeie",
         "traduzir", "translate", "reformat", "refactor", "refatorar", "profundamente", "thoroughly",
         "rigorosamente", "concurrency", "metodologia", "methodology", "architecture", "arquitetura",
         "analisar", "investigate", "investigar", "security", "seguranca", "strategy", "estrategia",
         "hypothesis", "statistical", "estatistica", "migration", "corrigir", "summarize", "extract")
FUZZY_SET = frozenset(FUZZY)


def plain(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def near(a, b):
    """True when a and b differ by one substitution, insertion, deletion or adjacent swap."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((k for k in range(len(short)) if short[k] != long_[k]), len(short))
    return short[i:] == long_[i + 1:]


def fix_typos(text):
    """Replace words one edit away from a FUZZY key word; returns (text, [(typo, word)])."""
    fixed = []

    def swap(match):
        word = match.group(0)
        if len(word) < 7 or word in FUZZY_SET:
            return word
        for key in FUZZY:
            if key[0] == word[0] and near(word, key):
                fixed.append((word, key))
                return key
        return word

    return re.sub(r"[a-z]+", swap, text), fixed


def own_words(prompt):
    """(the user's own text, attached characters): pasted blocks, fenced code and log lines cut out."""
    out, depth, pos, attached = [], 0, 0, 0
    for tag in PASTE_TAG.finditer(prompt):
        if depth == 0:
            out.append(prompt[pos:tag.start()])
        else:
            attached += tag.start() - pos
        depth = max(0, depth - 1) if tag.group(1) else depth + 1
        pos = tag.end()
    if depth == 0:
        out.append(prompt[pos:])
    else:
        attached += len(prompt) - pos  # an unclosed block runs to the end
    text = " ".join(out)
    attached += sum(len(m.group(0)) for m in FENCE.finditer(text))
    text = FENCE.sub(" ", text)
    kept, in_log = [], False
    for line in text.split("\n"):
        if LOG_LINE.match(line) or (in_log and line.startswith(("  ", "\t"))):
            attached += len(line)
            in_log = True
        else:
            kept.append(line)
            in_log = False
    return "\n".join(kept), attached


def analyze(prompt, structural=True, fuzzy=True):
    """Everything the verdict rests on: tier (or None), reason, scores, matches, features."""
    # settled: the silence is certain (nothing to route), as opposed to "no tier has enough evidence"
    result = {"tier": None, "reason": "", "signals": [], "scores": {}, "matches": [], "features": {},
              "typos": [], "settled": True}
    if not isinstance(prompt, str) or not prompt.strip():
        result["reason"] = "empty prompt"
        return result
    if prompt.lstrip().startswith("/"):
        result["reason"] = "slash command or skill: it runs as typed"
        return result
    if EVENT_PROMPT.match(prompt):
        result["reason"] = "event turn started by Claude Code, not a request"
        return result
    raw, attached = own_words(prompt)
    text = re.sub(r"\s+", " ", plain(raw)).strip()
    if fuzzy:
        text, result["typos"] = fix_typos(text)
    words = len(text.split())
    body = text[POLITE.match(text).end():].lstrip("¿¡\"'`([ ")
    polite = len(body) < len(text)
    # where each sentence's own words begin: the job is named in a sentence's first words
    starts = [0] + [m.end() + POLITE.match(body[m.end():]).end() for m in re.finditer(r"[.!?;:]\s+", body)]
    features = result["features"] = {
        "words": words, "attached_chars": attached, "questions": text.count("?"),
        "parts": len([p for p in re.split(r"[.;:?!\n]+", text) if len(p.split()) >= 2]),
        "polite_request": polite,
    }
    if words < (2 if structural and attached else MIN_WORDS):
        result["reason"] = (f"{words} own word(s): too short to judge, the conversation's current setup "
                            "carries on")
        return result

    kinds, lead = {}, {"chore": False, "standard": False, "deep": False}
    hits = {"chore": 0, "standard": 0, "deep": 0}
    for tier, kind, pattern, weight, leads in COMPILED:
        m, opens = None, False
        for found in pattern.finditer(body):
            if tier == "chore" and SUBORDINATE.search(body[:found.start()]):
                continue
            m = m or found
            if structural and leads and any(0 <= found.start() - s < LEAD_CHARS for s in starts):
                m, opens = found, True
                break
        if not m:
            continue
        lead[tier] = lead[tier] or opens
        kinds[kind] = kinds.get(kind, 0) + weight
        hits[tier] += 1
        result["matches"].append({"tier": tier, "kind": kind, "text": m.group(0).strip(), "weight": weight,
                                  "lead": opens})
    result["settled"] = False
    k = kinds.get
    chore = k("chore", 0) + (LEAD_BONUS if lead["chore"] else 0)
    nouns = min(1.0, k("noun", 0))
    standard = k("verb", 0) + k("light", 0) + k("weak", 0) + nouns + (LEAD_BONUS if lead["standard"] else 0)
    asks_thinking = k("strong", 0) + k("intent", 0) + k("depth", 0) + k("decision", 0)
    names_other_work = k("chore", 0) > 0 or k("verb", 0) > 0 or k("light", 0) > 0
    topics_count = asks_thinking > 0 or not names_other_work
    deep = asks_thinking + (k("topic", 0) if topics_count else 0) + (LEAD_BONUS if lead["deep"] else 0)
    structure = 0.0
    if structural and deep >= 1:
        structure += 1.0 if words >= 60 else 0.5 if words >= 30 else 0
        structure += 0.5 if features["questions"] >= 2 else 0
        structure += 0.5 if features["parts"] >= 3 else 0
        structure = min(STRUCTURE_CAP, structure)
        deep += structure
    features.update({"topics_count": topics_count, "structure_bonus": structure,
                     "lead": [t for t, v in lead.items() if v], "nouns_capped": nouns})
    result["scores"] = {"chore": chore, "standard": standard, "deep": deep}

    def verdict(tier, reason):
        result["tier"], result["reason"] = tier, reason
        if tier:
            ranked = sorted((m for m in result["matches"] if m["tier"] == tier),
                            key=lambda m: -m["weight"] - m["lead"])
            result["signals"] = [m["text"] for m in ranked[:3]]
        return result

    if THANKS.search(text) and words <= 8:
        result["settled"] = True
        return verdict(None, "thanks or approval, not a request")
    if DEFINITION.match(body):
        result["settled"] = True
        return verdict(None, "asks what something is: answered in place")
    # "... Can you find it and fix it?" is a request: a polite opener plus something to do
    last = body[max(m.end() for m in re.finditer(r"^|[.!?;:]\s+(?=\S)", body)):]
    names_work = k("chore", 0) > 0 or k("verb", 0) > 0 or k("light", 0) > 0
    request = ((polite and last == body) or bool(REQUEST.match(last))) and names_work
    asked = body.rstrip().endswith("?") and not request
    is_question = bool(QUESTION.match(body)) or asked
    features["question"] = is_question
    deep_wins = deep >= DEEP_MIN and deep >= standard and deep >= chore
    if is_question:
        if deep_wins and (hits["deep"] >= 2 or words >= 15):
            return verdict("deep", "a question with deep evidence from two matches or 15+ words")
        return verdict(None, "a question: answered in place unless clearly deep")
    if deep_wins:
        return verdict("deep", f"deep {deep:g} >= {DEEP_MIN:g} and not below chore {chore:g} or "
                               f"standard {standard:g}")
    if chore > standard and chore >= 1:
        if words > CHORE_MAX_WORDS:
            return verdict(None, f"chore words but {words} words long: more than a mechanical ask")
        return verdict("chore", f"chore {chore:g} > standard {standard:g}")
    if standard > chore and standard >= 1 and standard > nouns:
        return verdict("standard", f"standard {standard:g} > chore {chore:g}")
    return verdict(None, "no tier has enough evidence" if max(chore, standard, deep) < 1
                   else f"tie or weak evidence (chore {chore:g}, standard {standard:g}, deep {deep:g})")


def classify(prompt, structural=True, fuzzy=True):
    """(tier, signals) with tier in chore/standard/deep, or (None, []) when unclear."""
    result = analyze(prompt, structural, fuzzy)
    return result["tier"], result["signals"]
