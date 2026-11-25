/* Atena · preenchimento assistido da ficha da Extecamp (spec 21).
 *
 * Desde 25/11/2026 a ficha tem reCAPTCHA no envio: o robô não envia mais. Ele faz a
 * leitura no servidor (busca, cidade, parcelas) e a Central copia o resultado; este
 * script, injetado por um favorito NA ficha aberta pela pessoa, cola esses dados nos
 * campos. Quem marca o captcha e clica em Finalizar é a pessoa — o script nunca envia.
 *
 * Não traz dado nenhum embutido (é servido em rota pública): os dados chegam pelo
 * prompt, colados da área de transferência.
 */
(function () {
  var form = [].slice.call(document.forms).filter(function (f) { return f.elements.pf_nome; })[0];
  if (!form) { alert("Atena: abra primeiro a FICHA de inscrição da Extecamp (a página com Nome, CPF, endereço…)."); return; }
  var txt = prompt("Atena · cole aqui os dados copiados na Central (Cmd+V / Ctrl+V):");
  if (!txt) return;
  var d;
  try { d = JSON.parse(txt); } catch (e) { d = null; }
  if (!d || d.atena !== 1 || !d.campos) { alert("Atena: isso não são os dados copiados na Central. Clique em \"Copiar dados\" de novo."); return; }

  var norm = function (s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").trim().toLowerCase(); };
  // ex-aluno: a Extecamp já traz o nome dele. Nome diferente = ficha de outra pessoa.
  var naPag = norm(form.elements.pf_nome.value).split(" ")[0];
  if (naPag && naPag !== norm(d.nome).split(" ")[0] &&
      !confirm("Atena: esta ficha é de \"" + form.elements.pf_nome.value + "\", não de \"" + d.nome + "\".\n\nPreencher mesmo assim?")) return;

  var faltou = [], feitos = 0;
  // por NAME, não form.elements[n]: a ficha real repete id (id="pf_email" também no e-mail
  // alternativo, id="celular" no select do DDD) e form.elements casa id também.
  function el(n) {
    var l = form.querySelectorAll('[name="' + n + '"]');
    return l.length > 1 ? l : l[0];
  }
  function marca(e) { (e.length && !e.tagName ? e[0] : e).style.outline = "2px solid #1a9e55"; }
  function por(n, v) {
    var e = el(n);
    if (!e) { faltou.push(n); return; }
    if (e.length && !e.tagName) {                      // grupo de radio/checkbox
      var ok = false;
      [].forEach.call(e, function (x) { if (x.value === v) { x.checked = true; ok = true; } });
      if (!ok) { faltou.push(n); return; }
    } else if (e.tagName === "SELECT" && ![].some.call(e.options, function (o) { return o.value === v; })) {
      faltou.push(n); return;
    } else {
      e.value = v;
    }
    // change dispara o que a página faz quando a pessoa escolhe (ex.: UF -> carrega cidades)
    (e.length && !e.tagName ? e[0] : e).dispatchEvent(new Event("change", {bubbles: true}));
    marca(e); feitos++;
  }
  function esperaOpcao(n, v, ms) {                      // a lista de cidades chega por AJAX
    return new Promise(function (ok) {
      var t0 = Date.now();
      (function tenta() {
        var e = el(n);
        if (e && e.options && [].some.call(e.options, function (o) { return o.value === v; })) return ok();
        if (Date.now() - t0 > ms) return ok();
        setTimeout(tenta, 250);
      })();
    });
  }

  var c = d.campos, cidades = ["pf_cid", "pj_cid"], ufs = ["pf_est", "pj_est"];
  Object.keys(c).forEach(function (n) { if (cidades.indexOf(n) < 0 && ufs.indexOf(n) < 0) por(n, c[n]); });
  // UF -> cidade UM PAR POR VEZ: a página guarda o pedido AJAX numa global (xmlHttp);
  // trocar as duas UFs juntas faz o 2º pedido engolir o 1º e a cidade fica no spinner.
  function par(i) {
    var uf = ufs[i], cid = cidades[i];
    if (uf in c) por(uf, c[uf]);
    else if (cid in c && el(uf) && el(uf).value)   // ex-aluno: UF já certa, cidade muda
      el(uf).dispatchEvent(new Event("change", {bubbles: true}));
    if (!(cid in c)) return Promise.resolve();
    return esperaOpcao(cid, c[cid], 10000).then(function () { por(cid, c[cid]); });
  }
  par(0).then(function () { return par(1); }).then(function () {
    var cap = document.querySelector(".g-recaptcha");
    if (cap) cap.scrollIntoView({block: "center"});
    alert("Atena: " + feitos + " campo(s) preenchido(s) — contornados em verde." +
          (faltou.length ? "\n\nNÃO consegui preencher: " + faltou.join(", ") + ". Preencha à mão (o valor está na ficha, na Central)." : "") +
          "\n\nConfira, marque \"Não sou um robô\" e clique em Finalizar. Depois volte à Central e clique em \"Já enviei: conferir\".");
  });
})();
