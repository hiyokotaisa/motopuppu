// motopuppu/static/js/misskey_share.js
document.addEventListener('DOMContentLoaded', function() {
    // misskey_instance_domain は base.html でグローバルJavaScript変数として設定されている想定
    // var misskey_instance_domain = {{ misskey_instance_domain | tojson | safe }};

    document.body.addEventListener('click', function(event) {
        // ▼▼▼【変更】data-share-url 属性を持つボタンも対象にする ▼▼▼
        const shareButton = event.target.closest('.btn-share-misskey, [data-share-url]');
        
        if (!shareButton) {
            return;
        }

        if (typeof misskey_instance_domain === 'undefined' || !misskey_instance_domain) {
            console.error("Misskey instance domain is not defined in global scope. Check base.html.");
            alert("Misskeyインスタンスのドメインが設定されていません。");
            return;
        }

        const dataset = shareButton.dataset;

        // ▼▼▼【追加】data-share-url 属性がある場合の処理 ▼▼▼
        if (dataset.shareUrl) {
            fetch(dataset.shareUrl)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Server responded with status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.note_text) {
                        const encodedText = encodeURIComponent(data.note_text);
                        const shareUrl = `https://${misskey_instance_domain}/share?text=${encodedText}`;
                        window.open(shareUrl, '_blank', 'width=600,height=400,noopener,noreferrer');
                    } else {
                        console.error("Share note text not found in API response:", data);
                        alert("共有する内容の取得に失敗しました。");
                    }
                })
                .catch(error => {
                    console.error('Error fetching share note:', error);
                    alert('共有内容の取得中にエラーが発生しました。');
                });
            return; // このボタンの処理はここで終了
        }
        // ▲▲▲【追加】ここまで ▲▲▲

        // --- 以下は既存の data-type 属性を持つボタンの処理 ---
        const recordType = dataset.type;
        const vehicleName = dataset.vehicleName;
        const recordDate = dataset.date; // ISO 8601 format (e.g., "2023-05-08T10:20:30") or YYYY-MM-DD

        let shareText = "";
        const vehicleHashtag = vehicleName ? "\n#" + vehicleName.replace(/[\s#$&\+,:;=\?@\[\]\^`\{|\}~.]/g, '_') : '';
        const baseHashtags = "\n#もとぷっぷー";

        let displayDate = recordDate;
        if (recordDate) {
            try {
                const dateObj = new Date(recordDate);
                if (!isNaN(dateObj)) {
                    displayDate = dateObj.toLocaleDateString('ja-JP', { year: 'numeric', month: 'short', day: 'numeric' });
                } else {
                    console.warn("Could not parse recordDate to Date object:", recordDate);
                }
            } catch(e) {
                console.error("Error formatting date for Misskey share:", e);
            }
        }


        if (recordType === 'fuel') {
            const odo = dataset.odo;
            const volume = dataset.volume;
            const kpl = dataset.kpl;
            const cost = dataset.cost;
            const station = dataset.station;
            const notes = dataset.notes;

            shareText = `[${vehicleName}] 給油記録⛽\n` +
                        `日付: ${displayDate}\n` +
                        `走行距離: ${odo} km\n` +
                        `給油量: ${volume} L\n` +
                        (kpl ? `燃費: ${kpl} km/L\n` : '') +
                        (cost ? `費用: ${cost} 円\n` : '') +
                        (station ? `スタンド: ${station}\n` : '') +
                        (notes ? `メモ: ${notes}\n` : '') +
                        baseHashtags + " #給油記録" + vehicleHashtag;

        } else if (recordType === 'maintenance') {
            const odo = dataset.odo;
            const category = dataset.category;
            const description = dataset.description;
            const cost = dataset.cost;
            const location = dataset.location;
            const notes = dataset.notes;
            const contentSummary = category ? category : (description ? description.substring(0, 30) + (description.length > 30 ? '...' : '') : '整備');

            shareText = `[${vehicleName}] 整備記録🔧\n` +
                        `日付: ${displayDate}\n` +
                        `走行距離: ${odo} km\n` +
                        `内容: ${contentSummary}\n` +
                        (cost ? `費用: ${cost} 円\n` : '') +
                        (location ? `場所: ${location}\n` : '') +
                        (notes ? `メモ: ${notes}\n` : '') +
                        baseHashtags + " #バイク整備" + vehicleHashtag;

        } else if (recordType === 'note') {
            const category = dataset.category;
            const title = dataset.title;
            const content = dataset.content;
            const todosJson = dataset.todos;

            let categoryIcon = category === 'task' ? '✅' : '📝';
            let categoryHashtag = category === 'task' ? '#タスク' : '#ノート';
            let noteHeader = categoryIcon + (title ? ` ${title}` : ` ${category === 'task' ? 'タスク' : 'ノート'}記録`);

            shareText = noteHeader + "\n";
            if (vehicleName) { shareText += `車両: ${vehicleName}\n`; }
            shareText += `日付: ${displayDate}\n`;

            if (category === 'task' && todosJson && todosJson.length > 2) {
                try {
                    const todos = JSON.parse(todosJson);
                    if (Array.isArray(todos) && todos.length > 0) {
                        shareText += "TODO:\n";
                        todos.forEach((item) => {
                            if (item && typeof item.text !== 'undefined' && typeof item.checked !== 'undefined') {
                                shareText += `${item.checked ? '[x]' : '[ ]'} ${item.text}\n`;
                            }
                        });
                    }
                } catch (e) {
                    console.error("Error parsing TODO JSON for Misskey share:", e, "JSON string was:", todosJson);
                    if (content) {
                        shareText += `内容: ${content}\n`;
                    }
                }
            } else if (category === 'note' && content) {
                shareText += `内容: ${content}\n`;
            } else if (category === 'note' && !content) {
                shareText += `(内容なし)\n`;
            }

            shareText += baseHashtags + " " + categoryHashtag + (vehicleName ? vehicleHashtag : '');

        } else if (recordType === 'activity') {
            const title = dataset.title;
            const location = dataset.location;
            const weather = dataset.weather;
            const sessionsJson = dataset.sessionsJson; // 詳細ページ用
            const bestLap = dataset.bestLap;         // 一覧ページ用

            shareText = `[${vehicleName}] 活動ログ🏍️\n` +
                        `【${title}】\n` +
                        `日付: ${displayDate}\n` +
                        (location ? `場所: ${location}\n` : '');

            if (bestLap) {
                shareText += `ベストラップ: ${bestLap} 🏁\n`;
            }
            if (weather) {
                shareText += `天候: ${weather}\n`;
            }
            
            if (sessionsJson && sessionsJson.length > 2) {
                try {
                    const sessions = JSON.parse(sessionsJson);
                    if (Array.isArray(sessions) && sessions.length > 0) {
                        shareText += "\n--- セッション ---\n";
                        sessions.forEach((s, index) => {
                            shareText += `[${index + 1}] ${s.name}`;
                            if (s.best_lap && !bestLap) {
                                shareText += ` (ベスト: ${s.best_lap})`;
                            }
                            shareText += "\n";
                        });
                    }
                } catch(e) {
                    console.error("Error parsing sessions JSON for Misskey share:", e, "JSON string was:", sessionsJson);
                }
            }
            shareText += baseHashtags + " #活動ログ" + vehicleHashtag;

        } else if (recordType === 'touring') {
            const title = dataset.title;
            const spotsJson = dataset.spotsJson;
            let spots = [];
            try {
                if (spotsJson) {
                    spots = JSON.parse(spotsJson);
                }
            } catch(e) {
                console.error("Could not parse spots JSON for sharing:", e);
            }

            shareText = `ツーリングログ🏍️💨\n` +
                        `【${title}】\n` +
                        `日付: ${displayDate}\n` +
                        `車両: ${vehicleName}\n`;
            
            if (spots.length > 0) {
                shareText += "\n---\n";
                shareText += spots.join(' → ');
                shareText += "\n---";
            }

            shareText += baseHashtags + " #ツーリングログ" + vehicleHashtag;

        } else if (recordType === 'leaderboard') {
            const circuitName = dataset.circuitName;
            const rankingsJson = dataset.rankings;
            
            let rankings = [];
            try {
                rankings = JSON.parse(rankingsJson);
            } catch(e) {
                console.error("Error parsing rankings JSON for Misskey share:", e);
                alert("ランキング情報の取得に失敗しました。");
                return;
            }

            const rankIcons = ['🏆', '🥈', '🥉'];
            
            shareText = `【${circuitName} リーダーボード】\n\n`;

            rankings.forEach(item => {
                const icon = item.rank <= 3 ? rankIcons[item.rank - 1] : `${item.rank}位:`;
                shareText += `${icon} ${item.lap_time} (${item.username} / ${item.motorcycle_name})\n`;
            });

            const circuitHashtag = "\n#" + circuitName.replace(/[\s#$&\+,:;=\?@\[\]\^`\{|\}~.]/g, '_') + "リーダーボード";
            shareText += baseHashtags + circuitHashtag;
        }

        if (shareText) {
            const encodedText = encodeURIComponent(shareText);
            const shareUrl = `https://${misskey_instance_domain}/share?text=${encodedText}`;
            window.open(shareUrl, '_blank', 'width=600,height=400,noopener,noreferrer');
        } else {
            // shareUrlも無く、shareTextも生成されなかった場合
            if (!dataset.shareUrl) {
                console.warn("Share text was empty for record type:", recordType, "and dataset:", dataset);
                alert("共有する内容がありません。");
            }
        }
    });
});