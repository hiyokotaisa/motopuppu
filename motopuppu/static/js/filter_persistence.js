// motopuppu/static/js/filter_persistence.js
/**
 * フォームのフィルター状態をLocalStorageに保存し、ページ遷移後も維持する。
 * 2025-08-06 created by Gemini
 */
document.addEventListener('DOMContentLoaded', () => {

    class FilterPersistence {
        /**
         * @param {string} formId - 対象フォームのID
         * @param {string} storageKey - LocalStorageで使用するユニークなキー
         */
        constructor(formId, storageKey) {
            this.form = document.getElementById(formId);
            this.storageKey = storageKey;

            // 対象のフォームがページに存在しない場合は、何もしない
            if (!this.form) {
                return;
            }
            this.init();
        }

        /**
         * 初期化処理
         */
        init() {
            this.applyPersistedFiltersOnLoad();
            this.listenForFormChanges();
            this.overrideResetButton();
        }

        /**
         * フォームの現在の値をシリアライズしてオブジェクトで返す
         * @returns {Object}
         */
        getFormValues() {
            const formData = new FormData(this.form);
            const values = {};
            // 値が空でないフィールドのみをオブジェクトに格納する
            for (const [key, value] of formData.entries()) {
                if (value && value.trim() !== '') {
                    values[key] = value;
                }
            }
            return values;
        }

        /**
         * ページ読み込み時にLocalStorageの値に基づいてフォームを復元し、
         * 必要であればURLを同期させてリダイレクトする
         */
        applyPersistedFiltersOnLoad() {
            const savedFiltersJSON = localStorage.getItem(this.storageKey);
            const savedFilters = savedFiltersJSON ? JSON.parse(savedFiltersJSON) : {};

            // まず、保存された値をフォームの各フィールドに設定する
            Object.keys(savedFilters).forEach(key => {
                const element = this.form.elements[key];
                if (element) {
                    element.value = savedFilters[key];
                }
            });

            // 次に、現在のURLのクエリパラメータとLocalStorageの値を比較する
            const currentParams = new URLSearchParams(window.location.search);
            
            // 比較用のクリーンなURLSearchParamsオブジェクトを作成（フィルター関連のキーのみ）
            const currentFilterParams = new URLSearchParams();
            for(const [key, value] of currentParams.entries()){
                if(!['page', 'sort_by', 'order'].includes(key)){
                    currentFilterParams.set(key, value);
                }
            }
            const savedFilterParams = new URLSearchParams(savedFilters);

            // クエリ文字列を比較して同期が取れているか確認
            if (currentFilterParams.toString() !== savedFilterParams.toString()) {
                // ソート順は現在のURLから引き継ぐ
                if (currentParams.has('sort_by')) {
                    savedFilterParams.set('sort_by', currentParams.get('sort_by'));
                }
                if (currentParams.has('order')) {
                    savedFilterParams.set('order', currentParams.get('order'));
                }

                // URLを書き換えてリダイレクト
                window.location.search = savedFilterParams.toString();
            }
        }

        /**
         * フォームの値が変更されたときにLocalStorageに保存するリスナーを設定
         */
        listenForFormChanges() {
            // 'submit'ではなく'change'イベントを監視することで、
            // ユーザーが入力や選択を変更した瞬間に状態を保存します。
            this.form.addEventListener('change', () => {
                const values = this.getFormValues();
                if (Object.keys(values).length > 0) {
                    localStorage.setItem(this.storageKey, JSON.stringify(values));
                } else {
                    // 全てのフィルターがクリアされた場合はキーごと削除
                    localStorage.removeItem(this.storageKey);
                }
            });
        }

        /**
         * フォーム内のリセットボタンの挙動を上書きする
         */
        overrideResetButton() {
            // テンプレート内のリセットボタンを特定
            const resetButton = this.form.querySelector('a.btn-outline-secondary');
            if (resetButton) {
                resetButton.addEventListener('click', (event) => {
                    // デフォルトのリンク遷移を一旦停止
                    event.preventDefault();
                    
                    // LocalStorageからこのページのフィルター設定を削除
                    localStorage.removeItem(this.storageKey);
                    
                    // 元々ボタンに設定されていたURLに遷移
                    window.location.href = resetButton.href;
                });
            }
        }
    }

    // 各ページのフィルターフォームに対してインスタンスを生成する
    // これにより、このスクリプトはどちらのページでも機能します
    new FilterPersistence('fuel-filter-form', 'motopuppu_fuelLogFilters');
    new FilterPersistence('maintenance-filter-form', 'motopuppu_maintenanceLogFilters');
    new FilterPersistence('notes-filter-form', 'motopuppu_noteLogFilters'); // ▼▼▼ この行を追加 ▼▼▼
});