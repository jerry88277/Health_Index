# AVM 指標精確定義（primary-source 驗證版）

> 用途：M2/M3/M4 實作時的**唯一公式依據**，取代先前 AI 生成報告中可能不精確的式子。
> 來源：Cheng 團隊原始**專利**（一手），已逐式查證。查證日期 2026-06-01。
> 原則：repo 為唯一真相；任何與本檔衝突的轉述以本檔為準。

---

## 1. GSI（Global Similarity Index）— ⚠️ 存在兩種正典變體

GSI 本體＝**全空間 Mahalanobis 距離平方**，當前標準化製程資料 $\mathbf{z}_\ell$ 對模型集 $\mathbf{z}_M$、相關矩陣 $R$（$A=R^{-1}$）：

$$D_\ell^2 = (\mathbf{z}_\ell-\mathbf{z}_M)^\top R^{-1}(\mathbf{z}_\ell-\mathbf{z}_M)=\sum_{i=1}^{p}\sum_{j=1}^{p}a_{ij}\,z_{i\ell}z_{j\ell}$$

**兩份 Cheng 專利對正規化處理不同（皆為一手，皆有效）**：

| 來源 | GSI 定義 | 備註 |
|---|---|---|
| US7593912B2（Reliance Level, Eq.25） | $GSI = D_\ell^2$ | 不除 p |
| US8095484B2（AVM System, Eq.~38） | $GSI = D_\ell^2 / p$ | **除以參數數 p**（逐參數平均，使門檻跨維度可比） |

- 兩者只差常數 $1/p$，**概念上 $GSI \propto T^2_{full}$（全空間 Hotelling T²，相關矩陣形式，用全部 p 維不降維）**。
- **實作決定**：採 **US8095484B2 的 $GSI=D_\ell^2/p$**（完整 AVM 系統版；$1/p$ 讓門檻不隨維度膨脹，較適合泛化工多測點）。
- 門檻：$GSI_T = 3\times GSI_{LOO}$，$GSI_{LOO}$＝leave-one-out GSI 的 90% trimmed mean。

> 數值雷：$R$ 強共線性近奇異時 $R^{-1}$ 爆炸（全空間 Mahalanobis 通病）。我們在 L2 以 **PCA 保留段 T² + 殘差段 SPE** 作為 GSI 的數值穩健替身（見 §5），SPE 為 AVM 原生所無的補強。

## 2. DQI_x（製程資料品質指標）— Euclidean，非 Mahalanobis、非 SPE

來源：US8095484B2 Eq.28/30/31。PCA 取 k 個顯著主成分構成特徵抽取矩陣 $M$，新樣本投影 $\mathbf{a}=M\mathbf{X}$：

$$DQI_x = \sqrt{\sum_{j=1}^{k}\left(a_j - \bar{a}_j\right)^2}$$

- $\bar a_j$＝模型集第 j 個特徵均值。即**在 k 維 PCA 特徵空間中，新樣本對模型集中心的 Euclidean 距離（不加權）**。
- 與 GSI 區別：DQI_x＝**降維後 Euclidean**；GSI＝**全空間 Mahalanobis（$1/\lambda$ 加權）**。兩者都是「輸入相似度」但加權與空間不同。
- 門檻：$DQI_{x,T}=3\times DQI_{x,LOO}$（90% trimmed mean of LOO）。

> 注意：AVM 的 DQI_x 是**統計距離閘**，不含「NaN / 凍結值 / 超物理界限」這類原始效度檢查。本專案 L1 需**另加**這些工程性 sanity check（AVM 假設上游已處理）。

## 3. DQI_y（量測值品質指標）

來源：US8095484B2 Eq.36。以 **ART2** 將歷史量測分成 m 個 pattern，pattern $P_q$ 內以 **normalized variability (NV)** 定義 $DQI_{y_j}$；門檻 $DQI_{y,T}=Z_{score}(y_t)$，$y_t$＝最大可容忍量測值。$DQI_{y_j}>DQI_{y,T}$ 即判量測異常。
- 角色：只在**拿到實體 Y 要更新/校正模型**時把關標籤品質（本專案的模型更新路徑，非每筆 run）。

## 4. RI（Reliance Index）

來源：US7593912B2 Eq.4。NN conjecture 模型輸出分佈 $Z_{\hat y_{N_i}}$ 與 MR 參考模型輸出分佈 $Z_{\hat y_{r_i}}$（皆標準化 $\sigma=1$）之**重疊面積**：

$$RI = 2\int_{(Z_{\hat y_{N_i}}+Z_{\hat y_{r_i}})/2}^{\infty}\frac{1}{\sqrt{2\pi}\,\sigma}\,e^{-\frac{1}{2}\left(\frac{x-\mu}{\sigma}\right)^2}dx$$

- RI∈[0,1]，越接近 1 越可信；低於 $RI_T$ 則拒絕該次 VM、轉要求實體抽樣。
- **化工映射**：NN vs MR 雙模型 → 可用兩個獨立 soft sensor（如 PLS vs GPR）或 GPR 預測區間替代「重疊面積」語義。

## 5. T² / SPE（本專案 L2 增強，MSPC 標準）

PCA 保留 k 主成分，分數 $t_i=\mathbf{p}_i^\top\mathbf{x}$：

$$T^2=\sum_{i=1}^{k}\frac{t_i^2}{\lambda_i}\qquad SPE=\lVert(I-P_kP_k^\top)\mathbf{x}\rVert^2=\sum_{i=k+1}^{p}t_i^2$$

- $T^2$＝GSI 在可靠子空間的部分；$SPE$＝把 GSI 殘差段的 $1/\lambda$ 不穩定加權換成不加權平方和。
- $T^2$ 高/$SPE$ 正常＝操作點偏移；$SPE$ 高＝結構破壞（隱性飄移常落於此）。
- 控制限：$T^2_\alpha=\frac{k(n^2-1)}{n(n-k)}F_{\alpha,k,n-k}$；$SPE$ 用 Jackson–Mudholkar / Box $g\chi^2_h$。

## 6. 實作映射總表

| 判斷鏈層 | 採用指標 | 公式來源 | 實作備註 |
|---|---|---|---|
| L1 資料效度閘 | 原始 sanity check + DQI_x | 本專案 + US8095484B2 | sanity check 為 AVM 所無，需自加 |
| L2 多變量域 | **GSI=D²/p**＋T²＋**SPE** | US8095484B2 + MSPC | SPE 為 AVM 原生所無的補強 |
| L3 軟測量可信度 | Ŷ + RI（雙模型重疊 or GPR 區間） | US7593912B2 Eq.4 | 化工以 PLS/GPR 替代 NN/MR |
| 模型更新把關 | DQI_y | US8095484B2 Eq.36 | 僅拿到實體 Y 時啟用 |

## 來源
- US7593912B2 — Method for evaluating reliance level of a VM system（GSI Eq.25 無 1/p；RI Eq.4）: https://patents.google.com/patent/US7593912B2/en
- US8095484B2 — System and method for automatic virtual metrology（GSI=D²/p；DQI_x Eq.28/30/31；DQI_y Eq.36）: https://patents.google.com/patent/US8095484B2/en
- Huang & Cheng 2011, IEEE T-SM 24(3):445–454, DOI 10.1109/TSM.2011.2146006（DQI 期刊版）
- Cheng et al. 2008, IEEE T-SM 21(1):92–103, DOI 10.1109/TSM.2007.914373（RI/GSI 正典）
