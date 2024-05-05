from flask import Flask, request
from werkzeug.serving import make_server
import threading
import Lib.OnebotAPI as OnebotAPI
import Lib.Configs as Configs
import Lib.BotController as BotController
import Lib.EventManager as EventManager
import Lib.QQRichText as QQRichText
import Lib.Logger as Logger
import Lib.PluginManager as PluginManager
import Lib.QQDataCacher as QQDataCacher
import os

app = Flask(__name__)
api = OnebotAPI.OnebotAPI()
config = Configs.GlobalConfig()
logger = Logger.logger
request_list = []

work_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
data_path = os.path.join(work_path, "data")


# 上报
@app.route("/", methods=["POST"])
def post_data():
    data = BotController.Event(request.get_json())
    # 检测是否为重复上报
    logger.debug("收到上报: %s" % data)
    if data in request_list:
        return "ok", 204
    else:
        request_list.append(data)
    if len(request_list) > 100:
        request_list.pop(0)

    if data.post_type + "_type" in data:
        EventManager.Event((data.post_type, data[data.post_type + "_type"]), data)
    else:
        EventManager.Event(data.post_type, data)

    if data.post_type == "message" or data.post_type == "message_sent":
        # 私聊消息
        if data.message_type == "private":
            message = QQRichText.QQRichText(data["message"])
            QQDataCacher.UserData(data.user_id,
                                  data.sender.get("nickname"),
                                  data.sender.get("sex"),
                                  data.sender.get("age"))
            user = QQDataCacher.get_user_data(data.user_id)
            if data.sub_type == "friend":
                logger.info("收到好友 %s(%s) 的消息: %s (%s)" % (
                    user.nickname, user.user_id, str(message), data.message_id)
                            )
            elif data.sub_type == "group":
                group = QQDataCacher.get_group_data(data.group_id)
                logger.info("收到来自群 %s(%s) 内 %s(%s) 的临时会话消息: %s (%s)" % (
                    group.group_name, data.group_id,
                    user.nickname, user.user_id,
                    str(message), data.message_id
                )
                            )
            elif data.sub_type == "other":
                logger.info("收到来自 %s(%s) 的消息: %s (%s)" % (
                    user.nickname, user.user_id, str(message), data.message_id)
                            )

        # 群聊信息
        elif data.message_type == "group":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            message = QQRichText.QQRichText(data.message)

            logger.info("收到群 %s(%s) 内 %s(%s) 的消息: %s (%s)" % (
                group.group_name, group.group_id, user.get_group_name(), user.user_id, str(message),
                data.message_id))

            # 获取群文件夹路径
            group_path = os.path.join(data_path, "groups", str(data.group_id))
            # 如果获取群文件夹路径不存在, 则创建
            if not os.path.exists(group_path):
                os.makedirs(group_path)

    elif data.post_type == "request":
        # 加好友邀请
        if data.request_type == "friend":
            user = QQDataCacher.get_user_data(data.user_id)
            logger.info("收到来自 %s(%s) 的加好友请求: %s" %
                        (user.nickname, user.user_id, data.comment))
        # 加群邀请
        elif data.request_type == "group":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            if data.sub_type == "invite":
                logger.info("收到来自群 %s(%s) 内用户 %s(%s) 的加群邀请" %
                            (group.group_name, group.group_id, user.get_group_name(), user.user_id))
            elif data.sub_type == "add":
                logger.info("群 %s(%s) 收到来自用户 %s(%s) 的加群请求" %
                            (group.group_name, group.group_id, user.get_group_name(), user.user_id))

    elif data.post_type == "notice":
        # 群文件上传
        if data.notice_type == "group_upload":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            logger.info("群 %s(%s) 内 %s(%s) 上传了文件: %s" %
                        (group.group_name, group.group_id, user.get_group_name(), user.user_id, data.file))

        # 群管理员变动
        elif data.notice_type == "group_admin":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            operator = QQDataCacher.get_group_user_data(data.group_id, data.operator_id)
            if data.sub_type == "set":
                logger.info("群 %s(%s) 内, %s(%s) 将 %s(%s) 设为管理员" %
                            (group.group_name, group.group_id, operator.get_group_name(),
                             operator.user_id, user.get_group_name(), user.user_id))
            elif data.sub_type == "unset":
                logger.info("群 %s(%s) 内, %s(%s) 将 %s(%s) 取消管理员" %
                            (group.group_name, group.group_id, operator.get_group_name(),
                             operator.user_id, user.get_group_name(), user.user_id))

        # 群成员减少
        elif data.notice_type == "group_decrease":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            operator = QQDataCacher.get_group_user_data(data.group_id, data.operator_id)
            if data.sub_type == "leave":
                logger.info("群 %s(%s) 内 %s(%s) 退出了群聊" %
                            (group.group_name, group.group_id, user.get_group_name(), data.user_id))
            elif data.sub_type == "kick":
                logger.info(
                    "检测到 %s(%s) 被 %s(%s) 踢出了群聊 %s(%s)" %
                    (user.get_group_name(), user.user_id, operator.get_group_name(),
                     operator.user_id, group.group_name, data.group_id))
            elif data.sub_type == "kick_me" or user.user_id == config.user_id:
                logger.info("检测到Bot被 %s(%s) 踢出了群聊 %s(%s)" %
                            (operator.get_group_name(), operator.user_id, group.group_name, group.group_id))

        # 群成员增加
        elif data.notice_type == "group_increase":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            operator = QQDataCacher.get_group_user_data(data.group_id, data.operator_id)
            if data.sub_type == "approve":
                logger.info("群%s(%s) 内管理员 %s(%s) 通过了新成员 %s(%s) 的加群请求" %
                            (group.group_name, group.group_id, operator.get_group_name(),
                             operator.user_id, user.get_group_name(), user.user_id))
            elif data.sub_type == "invite":
                logger.info("群 %s(%s) 内 %s(%s) 邀请 %s(%s) 加入了群聊" %
                            (group.group_name, group.group_id, operator.get_group_name(),
                             operator.user_id, user.get_group_name(), user.user_id))

        # 群禁言
        elif data.notice_type == "group_ban":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            operator = QQDataCacher.get_group_user_data(data.group_id, data.operator_id)
            # 禁言
            if data.sub_type == "ban":
                logger.info("群 %s(%s) 内 %s(%s) 被 %s(%s) 禁言了" %
                            (group.group_name, group.group_id, user.get_group_name(),
                             user.user_id, operator.get_group_name(), operator.user_id))
            # 解除禁言
            elif data.sub_type == "lift_ban":
                logger.info("群 %s(%s) 内 %s(%s) 被 %s(%s) 解除禁言" %
                            (group.group_name, group.group_id, user.get_group_name(),
                             user.user_id, operator.get_group_name(), operator.user_id))

        # 好友添加
        elif data.notice_type == "friend_add":
            user = QQDataCacher.get_user_data(data.user_id)
            logger.info("检测到新好友 %s(%s) 添加了Bot" %
                        (user.nickname, user.user_id))

        # 群消息撤回
        elif data.notice_type == "group_recall":
            group = QQDataCacher.get_group_data(data.group_id)
            user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
            logger.info("群 %s(%s) 内 %s(%s) 撤回了一条消息: %s" %
                        (group.group_name, group.group_id, user.get_group_name(), user.user_id, data.message_id))

        # 好友消息撤回
        elif data.notice_type == "friend_recall":
            user = QQDataCacher.get_user_data(data.user_id)
            logger.info("检测到好友 %s(%s) 撤回了一条消息: %s" %
                        (user.user_id, user, data.message_id))

        elif data.notice_type == "notify":
            # 群内戳一戳
            if data.sub_type == "poke":
                group = QQDataCacher.get_group_data(data.group_id)
                user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
                target = QQDataCacher.get_group_user_data(data.group_id, data.target_id)
                logger.info("收到群 %s(%s) 内 %s(%s) 戳了戳 %s(%s)" %
                            (group.group_name, group.group_id, user.get_group_name(), user.user_id,
                             target.get_group_name(), target.user_id))
            # 红包运气王
            elif data.sub_type == "lucky_king":
                group = QQDataCacher.get_group_data(data.group_id)
                user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
                target = QQDataCacher.get_group_user_data(data.group_id, data.target_id)
                logger.info("群 %s(%s) 内 %s(%s) 发送的红包, %s(%s)是运气王" %
                            (group.group_name, group.group_id, user.get_group_name(), user.user_id,
                             target.get_group_name(), target.user_id))

            # 群成员荣誉变更
            elif data.sub_type == "honor":
                group = QQDataCacher.get_group_data(data.group_id)
                user = QQDataCacher.get_group_user_data(data.group_id, data.user_id)
                if data.honor_type == "talkative":
                    logger.info("群 %s(%s) 内 %s(%s) 获得了龙王" %
                                (group.group_name, group.group_id, user.get_group_name(), user.user_id))
                elif data.honor_type == "performer":
                    logger.info("群 %s(%s) 内 %s(%s) 获得了群聊之火" %
                                (group.group_name, group.group_id, user.get_group_name(), user.user_id))
                elif data.honor_type == "emotion":
                    logger.info("群 %s(%s) 内 %s(%s) 获得了快乐源泉" %
                                (group.group_name, group.group_id, user.get_group_name(), user.user_id))

    # 若插件包含main函数则运行
    for plugin in PluginManager.plugins:
        try:
            if not callable(plugin["plugin"].main):
                continue
        except AttributeError:
            continue

        logger.debug("执行插件%s" % plugin["name"])
        try:
            plugin_thread = threading.Thread(
                target=plugin["plugin"].main,
                args=(
                    data.event_json,
                    work_path)
            )
            plugin_thread.start()
        except Exception as e:
            logger.error("执行插件%s时发生错误：%s" % (plugin["name"], repr(e)))
            continue

    return "ok", 204


server = make_server(config.server_host, config.server_port, app, threaded=True)
