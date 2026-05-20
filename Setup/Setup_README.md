# Setup Reference

This guide walks you through everything you need before running the plays. Follow the steps in order — by the end you'll have all your values in the Setup Reference and be ready to run plays with nothing but bash commands and notebooks.

**Keep `setup_reference.html` open in your browser throughout this guide.** Fill in each field as you collect it — the deploy command auto-generates as you go.

---

## Step 1 — Collect Your Tableau Information

Open your Tableau Cloud site and collect the following. Fill each value into the Setup Reference as you go.

**1.1 — Pod hostname**
Look at your Tableau Cloud URL. The pod hostname is the first part:
```
https://10ay.online.tableau.com/#/site/your-site/...
        ───────────────────────
        copy this entire hostname
```
Fill in **Pod hostname** in the Setup Reference.

**1.2 — Site contentUrl slug**
In the same URL, the slug comes after `/site/`:
```
https://10ay.online.tableau.com/#/site/vdsapi82-5507b0d30c/...
                                       ───────────────────
                                       copy this entire slug
```
The site contentUrl slug is the alphanumeric string after `/site/` — it may look something like `vdsapi82-5507b0d30c` or `mycompany` depending on how your site was configured. Copy the entire string between `/site/` and the next `/`.

Fill in **Site contentUrl slug** in the Setup Reference. Leave blank if you are on Tableau Server default site.

**1.3 — Decide Your PAT Name**
Decide on a name for your Tableau Personal Access Token now e.g. `fabric-bridge-pat` — fill in **PAT name** in the Setup Reference.

> You will generate the actual PAT in Step 2.3, immediately after Key Vault is ready so you can paste the secret directly without storing it anywhere in the meantime. The PAT must be created by a user with **Site Administrator** role — a non-admin PAT will return a partial inventory and respect row-level security.

---

## Step 2 — Set Up Azure Key Vault

This is the most critical setup step. Take your time and follow each sub-step carefully.

### 2.1 — Create the Key Vault

1. Go to [portal.azure.com](https://portal.azure.com)
2. Search **Key Vaults** → **Create**
3. Fill in:
   - **Subscription** — select your subscription. Fill in **Subscription ID** in the Setup Reference (use the GUID format — copy from the subscription overview page, not the display name)
   - **Resource group** — select an existing one or create new. Fill in **Resource group** in the Setup Reference
   - **Key vault name** — choose a name e.g. `tableau-fabric-kv`. Fill in **Key Vault name** in the Setup Reference
   - **Region** — choose your region. Fill in **Region** in the Setup Reference. **Use the same region for everything in this play** (Key Vault, Logic App, API connection)
   - **Permission model** — select **Azure role-based access control (RBAC)**
4. Click **Review + create** → **Create**
5. Wait for deployment to complete → **Go to resource**

### 2.2 — Assign Yourself as Key Vault Secrets Officer

You need to assign yourself the Secrets Officer role before you can create secrets.

1. In your new Key Vault → **Access control (IAM)** → **Add role assignment**
2. Role: search for and select **Key Vault Secrets Officer**
3. Click **Next** → **Select members** → search for your name → select yourself → **Select**
4. Click **Review + assign** → **Assign**

> ⚠️ **RBAC propagation:** After assigning the role, wait 2-3 minutes before proceeding. If you immediately try to create a secret and see "The operation is not allowed by RBAC", wait and refresh.

### 2.3 — Generate Your PAT and Store It Immediately

Now that Key Vault is ready and your role is assigned, generate the PAT and paste it directly into Key Vault in one motion — no temp storage needed.

**Generate the PAT:**
1. Go back to your Tableau Cloud site → click your avatar (top right) → **Account Settings**
2. Scroll to **Personal Access Tokens** → **Add**
3. Enter the PAT name you decided in Step 1.3
4. Set expiration to the **maximum allowed** (up to 1 year) — short expiration will silently break the Logic App
5. Click **Create** — keep this window open, you need the secret value in the next step

**Immediately store it in Key Vault:**
1. Switch to your Key Vault browser tab → **Objects** → **Secrets** → **Generate/Import**
2. **Upload options:** Manual
3. **Name:** choose a secret name e.g. `tableau-pat-secret`. Fill in **Key Vault secret name** in the Setup Reference
4. **Secret value:** paste your Tableau PAT secret value directly from the Tableau window
5. Click **Create**

> ✅ You can now close the Tableau PAT window — the secret is safely stored in Key Vault.

### 2.4 — Configure Key Vault Networking

1. Key Vault → **Settings** → **Networking**
2. Check **Allow trusted Microsoft services to bypass this firewall**
3. Click **Save**

> ⚠️ **Known limitation:** On some Consumption Logic App configurations the trusted services bypass is insufficient. If the Logic App fails to retrieve the secret at runtime, set **Allow public access from all networks** temporarily. For production use Logic Apps Standard.

### 2.5 — Get Your Deploy Command

At this point your Setup Reference should have:
- ✅ Pod hostname
- ✅ Site contentUrl slug
- ✅ PAT name
- ✅ Subscription ID (GUID)
- ✅ Resource group
- ✅ Region
- ✅ Logic App name (choose one now e.g. `tableau-vds-logic-app`)
- ✅ Key Vault name
- ✅ Key Vault secret name

Fill in **Logic App name** in the Setup Reference. The **Play 1 — Full deploy sequence** at the bottom of the Setup Reference should now be fully populated. **Do not run it yet** — you need the Datasource LUID from Step 3 first.

---

## Step 3 — Set Up Your Fabric Workspace

### 3.1 — Create Folders

In your Fabric workspace:
1. **New** → **Folder** → name it `Notebooks`
2. **New** → **Folder** → name it `Lakehouses`

### 3.2 — Create Two Lakehouses

**Metadata Lakehouse** (stores Tableau governance metadata):
1. Open the `Lakehouses` folder → **New** → **Lakehouse**
2. Name it `Metadata_Lakehouse` (or your preferred name — note it for Cell 1 of the notebooks)
3. Fill in **Metadata lakehouse name** in the Setup Reference

**Data Lakehouse** (stores actual datasource data):
1. Still in `Lakehouses` folder → **New** → **Lakehouse**
2. Name it `h1_ultrastore` (or your preferred name — note it for Cell 1 of the notebooks)
3. Fill in **Data lakehouse name** in the Setup Reference

### 3.3 — Get Your Fabric Workspace ID

1. In your Fabric workspace, look at the browser URL:
   ```
   https://app.fabric.microsoft.com/groups/YOUR-WORKSPACE-ID/...
   ```
2. Copy the GUID after `/groups/` → fill in **Workspace ID** in the Setup Reference

### 3.4 — Grant Key Vault Access to Fabric Notebooks

Plays 2, 3, and 4 use managed identity to retrieve the Tableau PAT from Key Vault. Grant access:

1. Azure Portal → your Key Vault → **Access control (IAM)** → **Add role assignment**
2. Role: **Key Vault Secrets User**
3. Assign access to: **Managed identity**
4. Click **Select members** → change **Managed identity** dropdown to **Microsoft Fabric** → select your workspace
5. **Review + assign**

### 3.5 — Enable Fabric API Access (required for Play 4)

1. Go to [Fabric Admin Portal](https://app.fabric.microsoft.com/admin-portal) → **Tenant settings**
2. Search for **"Service principals can use Fabric APIs"** → **Enable**
3. This is a one-time tenant setting

### 3.6 — Import Notebooks

1. Open the `Notebooks` folder in your Fabric workspace
2. **Import** → upload all four notebooks from the repo:
   - `Play2_Tableau_Metadata_Bridge.ipynb`
   - `Play3_Tableau_VDS_Bridge.ipynb`
   - `Play4_Tableau_Semantic_Model_Generator.ipynb`
   - `Play1_Agent_Instructions_Generator.ipynb`

### 3.7 — Run the Instructions Generator and Get Your Datasource LUID

This notebook resolves your datasource LUID (required for the Play 1 deploy command) and generates your Foundry agent instructions.

1. Open `Play1_Agent_Instructions_Generator.ipynb`
2. Attach a lakehouse (any — it just needs one attached to run)
3. Fill in Cell 1:
   - `PAT_NAME` — your PAT name from Step 1.3
   - `KV_URL` — `https://your-keyvault-name.vault.azure.net/`
   - `KV_SECRET_NAME` — your secret name from Step 2.3
   - `POD` — your pod hostname from Step 1.1
   - `SITE` — your site contentUrl slug from Step 1.2
   - `DATASOURCE_NAME` — exact display name of your target datasource
4. Run all cells
5. From the Cell 5 output:
   - Copy the **Datasource LUID** → fill in **Datasource LUID** in the Setup Reference
   - Copy the **agent instructions** block → save it for Step 4

The Setup Reference deploy command is now fully populated. ✅

---

## Step 4 — Deploy Play 1 (Logic App)

1. Open [Azure Cloud Shell](https://portal.azure.com/#cloudshell) in your browser
2. Upload both Bicep files from the Play 1 folder: `deploy_logicapp.bicep` and `deploy_connection.bicep`
   - Click **Manage files** → **Upload** → select both files
3. Copy the full deploy sequence from the bottom of the Setup Reference and paste it into Cloud Shell
4. **While the command is sleeping (3 minutes):** go to Azure Portal → **API Connections** → find `keyvault-{your-region}` → **General** → **Edit API connection** → **Authorize** → **Save**
5. Wait for the full sequence to complete
6. Go to your Logic App → designer → **When an HTTP request is received** trigger → copy the **HTTP POST URL**
7. Fill in **Logic App trigger URL** in the Setup Reference

---

## Step 5 — Configure the OpenAPI Spec and Create the Foundry Agent

1. Open `Play1/openapi_spec.json` from the repo
2. Replace `YOUR_LOGIC_APP_TRIGGER_URL` with the base URL (everything before the `?`) from Step 4
3. Replace `YOUR_LOGIC_APP_SIG` with the sig value (everything after `sig=`) from the trigger URL
4. Go to [ai.azure.com](https://ai.azure.com) → your project → **Agents** → **New agent**
5. Model: **GPT-4o**
6. Paste the agent instructions from Step 3.7 into the **Instructions** field
7. **Tools** → **Add** → **Custom** → **OpenAPI** → paste the updated spec
8. Authentication: **Anonymous**
9. **Save** → test with a natural language question about your data

---

## You're Ready

With setup complete:
- Run **Play 2** first (Metadata Bridge) — attach `Metadata_Lakehouse` as default lakehouse
- Run **Play 3** next (VDS Bridge) — attach `h1_ultrastore` as default, `Metadata_Lakehouse` as secondary
- Run **Play 4** last (Semantic Model Generator) — attach any lakehouse as default
- **Play 1** (Foundry agent) is ready to use immediately

See each play's README for Cell 1 values and known issues.
