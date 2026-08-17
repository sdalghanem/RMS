        const subSelect = document.getElementById("sub-program-select");
      const subDetails = document.getElementById("sub-details");
      const addSelectedBtn = document.getElementById("add-selected");
      const tableBody = document.querySelector("#beneficiaries-table tbody");
      const emptyRow = document.getElementById("empty-row");
      const totalEl = document.getElementById("total-amount");
      const subAfterEl = document.getElementById("sub-after");
      const submitBtn = document.getElementById("submit-btn");
      const uniformAmountInput = document.getElementById("uniform-amount");
      const applyUniformBtn = document.getElementById("apply-uniform");
      const clearUniformBtn = document.getElementById("clear-uniform");

      let subRemaining = 0;

      if (applyUniformBtn) {
        applyUniformBtn.addEventListener("click", function () {
          const val = parseFloat(uniformAmountInput.value || 0);
          if (val <= 0) return;

          document.querySelectorAll('input[name="amounts[]"]').forEach(inp => {
            inp.value = val.toFixed(2);
          });

          updateTotals();
        });
      }

      if (clearUniformBtn) {
        clearUniformBtn.addEventListener("click", function () {

          document.querySelectorAll('input[name="amounts[]"]').forEach(inp => {
            inp.value = "";
          });

          if (uniformAmountInput) {
            uniformAmountInput.value = "";
          }

          updateTotals();

        });
      }

      function getSubEl(id) {
        return document.querySelector(`#sub-data .sub-prog[data-id="${id}"]`);
      }
      function renderSubDetails(el) {

        if (!el) {
          subDetails.innerHTML = `
            <div class="alert alert-warning mb-0">
                تعذر العثور على بيانات البرنامج.
            </div>
        `;
          return;
        }

        const balance = Number(el.dataset.balance || 0);

        subRemaining = balance;
        const summaryBalance = document.getElementById("summary-balance");

if (summaryBalance) {
    summaryBalance.innerText =
        balance.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }) + " ر.س";
}
        subDetails.innerHTML = `
        <div class="alert alert-light border mb-0 text-center">

            <div class="text-muted small">
                الرصيد الحالي
            </div>

            <div class="display-6 fw-bold text-success mt-2">
                ${balance.toLocaleString('en-US', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        })} ر.س
            </div>

        </div>
    `;

        updateTotals();
      }
      function updateTotals() {

        let total = 0;

        document.querySelectorAll('input[name="amounts[]"]').forEach(inp => {
          total += parseFloat(inp.value || 0);
        });

        if (totalEl) {
          totalEl.innerText = total.toFixed(2);
        }

        const after = subRemaining - total;
        const summaryTotal = document.getElementById("summary-total");
const summaryAfter = document.getElementById("summary-after");

if (summaryTotal) {
    summaryTotal.innerText =
        total.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
}

if (summaryAfter) {
    summaryAfter.innerText =
        after.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
}
        if (subAfterEl) {
          subAfterEl.innerText = after.toFixed(2) ;

          if (after < 0) {
            subAfterEl.classList.add("text-danger");
          } else {
            subAfterEl.classList.remove("text-danger");
          }
        }

        if (submitBtn) {
          submitBtn.disabled = !(subSelect.value && total > 0 && after >= 0);
        }

      }

      subSelect.addEventListener("change", function () {
        const id = this.value;

        if (!id) {
          subDetails.innerHTML = "اختر برنامجًا فرعيًا لعرض الرصيد.";
          subRemaining = 0;
          updateTotals();
          return;
        }

        const el = getSubEl(id);

        if (el) {
          renderSubDetails(el);
        }
      });

      addSelectedBtn.addEventListener("click", function () {
        const checks = document.querySelectorAll(".bene-check:checked");

        if (!checks.length) return;

        if (emptyRow) emptyRow.remove();

        checks.forEach((c) => {

          const id = c.dataset.id;
          const name = c.dataset.name;
          const nn = c.dataset.nn;

          if (document.querySelector(`input[name="beneficiary_ids[]"][value="${id}"]`)) {
            return;
          }



          const tr = document.createElement("tr");
         tr.innerHTML = `

<td class="text-start">

    <div class="fw-bold">
        ${name}
    </div>

    <div class="small text-muted">
        ${nn}
    </div>

    <input
        type="hidden"
        name="beneficiary_ids[]"
        value="${id}">

</td>

<td class="text-center">

    <input
        type="number"
        step="0.01"
        min="0"
        name="amounts[]"
        class="form-control amount-input text-center"
        placeholder="0.00">

</td>

<td class="text-center">

    <button
        type="button"
        class="btn btn-sm btn-outline-danger remove-row">

        <i class="bi bi-trash"></i>

    </button>

</td>

`;

          tableBody.appendChild(tr);
          document.getElementById("selected-count").innerText =
            tableBody.querySelectorAll("tr").length;
          const uVal = parseFloat(uniformAmountInput.value || 0);

          if (uVal > 0) {
            tr.querySelector('input[name="amounts[]"]').value = uVal.toFixed(2);
          }

          c.checked = false;
        });

        
        updateTotals();

        if (!tableBody.querySelectorAll("tr").length) {
          tableBody.innerHTML =
            `<tr id="empty-row">
          <td colspan="4" class="text-center text-muted py-3">
            لم يتم اختيار مستفيدين بعد.
          </td>
        </tr>`;
        }
      });

      document.addEventListener("click", function (e) {

        if (e.target.closest(".remove-row")) {

          e.target.closest("tr").remove();
          document.getElementById("selected-count").innerText =
            tableBody.querySelectorAll("tr").length - 1;
          
          updateTotals();

          if (!tableBody.querySelectorAll("tr").length) {
            tableBody.innerHTML =
              `<tr id="empty-row">
            <td colspan="3" class="text-center text-muted py-3">
              لم يتم اختيار مستفيدين بعد.
            </td>
          </tr>`;
          }
        }
      });



      document.addEventListener("input", function (e) {

        if (e.target.matches(".amount-input")) {
          updateTotals();
        }

      });

      updateTotals();

      const selectAllBene = document.getElementById("select-all-bene");

     function getVisibleChecks() {

    return Array.from(document.querySelectorAll(".bene-check"))
        .filter(ch => {
            const row = ch.closest("tr");
            return row && row.style.display !== "none";
        });

}

      if (selectAllBene) {

        selectAllBene.addEventListener("change", function () {

          const checks = getVisibleChecks();

          checks.forEach(ch => ch.checked = this.checked);

        });

       document.addEventListener("change", function (e) {

    if (!e.target.classList.contains("bene-check")) return;

    const checks = getVisibleChecks();

    const allChecked = checks.length && checks.every(ch => ch.checked);
    const noneChecked = checks.every(ch => !ch.checked);

    selectAllBene.checked = allChecked;
    selectAllBene.indeterminate = !allChecked && !noneChecked;

});

      }




      // ===============================
// فلترة المستفيدين بدون Reload
// ===============================

const applyFilterBtn = document.getElementById("apply-filter");

if (applyFilterBtn) {

    applyFilterBtn.addEventListener("click", function () {

        const education = document.querySelector('[name="education_level"]').value;
        const gender = document.querySelector('[name="gender"]').value;
        const health = document.querySelector('[name="health_status"]').value;
        const disease = document.querySelector('[name="type_disease"]').value;
        const diseaseQ = document.querySelector('[name="disease_q"]').value.trim().toLowerCase();

const rows = document.querySelectorAll("#beneficiaries-list tbody tr[data-education]");
        rows.forEach(function (row) {

            let show = true;

            if (education && row.dataset.education !== education)
                show = false;

            if (gender && row.dataset.gender !== gender)
                show = false;

            if (health && row.dataset.health !== health)
                show = false;

            if (disease && row.dataset.disease !== disease)
                show = false;

            if (diseaseQ &&
                !row.dataset.diseaseName.toLowerCase().includes(diseaseQ))
                show = false;

            row.style.display = show ? "" : "none";

        });

    });

}

// ===============================
// فلترة المستفيدين مباشرة
// ===============================

function filterBeneficiaries() {

    const education = document.querySelector('[name="education_level"]').value;
    const gender    = document.querySelector('[name="gender"]').value;
    const health    = document.querySelector('[name="health_status"]').value;
    const disease   = document.querySelector('[name="type_disease"]').value;
    const diseaseQ  = document.querySelector('[name="disease_q"]').value.trim().toLowerCase();

    document.querySelectorAll("#beneficiaries-list tbody tr").forEach(function(row){

        if (!row.dataset.education) return;

        let show = true;

const rowEducation = row.dataset.education || "";

if (education !== "" && rowEducation !== education) {
    show = false;
}
        if (gender && row.dataset.gender !== gender)
            show = false;

        if (health && row.dataset.health !== health)
            show = false;

        if (disease && row.dataset.disease !== disease)
            show = false;

        if (diseaseQ &&
            !row.dataset.diseaseName.toLowerCase().includes(diseaseQ))
            show = false;

        row.style.display = show ? "" : "none";

    });

}
 


// تشغيل الفلاتر مباشرة

[
    'education_level',
    'gender',
    'health_status',
    'type_disease'
].forEach(function(name){

    const el = document.querySelector(`[name="${name}"]`);

    if(el){
        el.addEventListener("change", filterBeneficiaries);
    }

});

const diseaseInput = document.querySelector('[name="disease_q"]');

if(diseaseInput){
    diseaseInput.addEventListener("input", filterBeneficiaries);
}