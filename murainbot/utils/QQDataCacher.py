"""
QQ数据缓存
"""
import time
import threading

from ..core import OnebotAPI, ConfigManager
from . import Logger, TimerManager

NotFetched = type("NotFetched", (), {"__getattr__": lambda _, __: NotFetched,
                                     "__repr__": lambda _: "NotFetched",
                                     "__bool__": lambda _: False})
api = OnebotAPI.api
logger = Logger.get_logger()

if ConfigManager.GlobalConfig().qq_data_cache.enable:
    expire_time = ConfigManager.GlobalConfig().qq_data_cache.expire_time
else:
    expire_time = 0

# 事件中可能携带的群信息字段 (OneBot v11 标准字段名)
GROUP_INFO_FIELDS = ("group_name", "member_count", "max_member_count")
# 事件中可能携带的用户通用信息字段
USER_INFO_FIELDS = ("nickname", "sex", "age", "remark")


def _to_not_fetched(v):
    """
    将 None 转换为 NotFetched (视为尚未获取), 其余值原样返回
    """
    return NotFetched if v is None else v


class QQDataItem:
    """
    QQ数据缓存类
    """

    def __init__(self):
        self._data = NotFetched  # 数据
        self.last_update = time.time()  # 最后刷新时间
        self.last_use = -1  # 最后被使用时间（数据被使用）

    def refresh_cache(self):
        """
        刷新缓存
        Returns:
            None
        """
        self.last_update = time.time()

    def update(self, **kwargs):
        """
        用上游提供的数据更新缓存 (例如从事件中解析出的信息).
        更新成功后重置缓存过期时间, 使后续访问命中缓存而不再调用 API.
        值为 None 的字段将被视为尚未获取 (NotFetched).
        Args:
            **kwargs: 要更新的数据字段
        Returns:
            None
        """
        if not kwargs:
            return
        for k, v in kwargs.items():
            self._data[k] = _to_not_fetched(v)
        self.last_update = time.time()
        self.last_use = time.time()


class UserData(QQDataItem):
    """
    QQ用户数据缓存类
    """

    def __init__(
            self,
            user_id: int,
            nickname: str = NotFetched,
            sex: str = NotFetched,
            age: int = NotFetched,
            is_friend: bool = NotFetched,
            remark: str | None = NotFetched,  # 此值仅在是好友的时候会存在
            **kwargs  # 其他字段（实现端特有字段等），将一并缓存，可通过属性访问
    ):
        super().__init__()
        self._user_id = user_id
        self._data = {
            "user_id": user_id,
            "nickname": nickname,
            "sex": sex,
            "age": age,
            "is_friend": is_friend,
            "remark": remark
        }
        self.update(**kwargs)

    def refresh_cache(self):
        """
        刷新缓存
        Returns:
            None
        """
        if int(self._user_id) <= 0:
            logger.warn(f"获取用户{self._user_id}缓存信息失败: user_id小于等于0")
            return
        try:
            data = api.get_stranger_info(self._user_id)
            for k in data:
                self._data[k] = _to_not_fetched(data[k])
            self._data["is_friend"] = NotFetched
            self._data["remark"] = NotFetched
        except Exception as e:
            logger.warn(f"获取用户{self._user_id}缓存信息失败: {repr(e)}")
            return

    def __getattr__(self, item):
        if item == "_data" or item == "data":
            return self._data

        # 好友信息未知时才查询好友列表确认; 若已被事件等上游注入则直接使用缓存值
        if item in ["remark", "is_friend"] and self._data.get(item) == NotFetched:
            try:
                res = api.get_friend_list()
                for friend in res:
                    if friend["user_id"] == self._user_id:
                        self._data["remark"] = friend["remark"]
                        self._data["is_friend"] = True
                        break
                else:
                    self._data["is_friend"] = False
                    self._data["remark"] = None
            except Exception as e:
                logger.warn(f"获取用户{self._user_id}是否为好友失败: {repr(e)}")
                return None

        if self._data.get(item) == NotFetched or time.time() - self.last_update > expire_time:
            self.refresh_cache()

        if self._data.get(item) == NotFetched:
            return None

        if item in self._data:
            self.last_use = time.time()

        return self._data.get(item)

    def get_nickname(self) -> str:
        """
        获取昵称（如果有备注名优先返回备注名）
        Returns:
            昵称
        """
        return self.remark or self.nickname

    def __repr__(self):
        return f"UserData(user_id={self._user_id})"


class GroupMemberData(QQDataItem):
    """
    QQ群成员数据缓存类
    """

    def __init__(
            self,
            group_id: int,
            user_id: int,
            nickname: str = NotFetched,
            card: str = NotFetched,
            sex: str = NotFetched,
            age: int = NotFetched,
            area: str = NotFetched,
            join_time: int = NotFetched,
            last_sent_time: int = NotFetched,
            level: str = NotFetched,
            role: str = NotFetched,
            unfriendly: bool = NotFetched,
            title: str = NotFetched,
            title_expire_time: int = NotFetched,
            card_changeable: bool = NotFetched,
            **kwargs  # 其他字段（如实现端的 shut_up_end_time 等），将一并缓存，可通过属性访问
    ):
        super().__init__()
        self._group_id = group_id
        self._user_id = user_id
        self._data = {
            "group_id": group_id,
            "user_id": user_id,
            "nickname": nickname,
            "card": card,
            "sex": sex,
            "age": age,
            "area": area,
            "join_time": join_time,
            "last_sent_time": last_sent_time,
            "level": level,
            "role": role,
            "unfriendly": unfriendly,
            "title": title,
            "title_expire_time": title_expire_time,
            "card_changeable": card_changeable,
        }
        self.update(**kwargs)

    def refresh_cache(self):
        """
        刷新缓存
        Returns:
            None
        """
        if int(self._group_id) <= 0 or int(self._user_id) <= 0:
            logger.warn(f"获取群{self._group_id}中成员{self._user_id}缓存信息失败: group_id或user_id小于等于0")
            return
        try:
            # 不使用 no_cache: 强制刷新会绕过实现端自身的缓存, 在部分实现端上会显著变慢
            data = api.get_group_member_info(self._group_id, self._user_id)
            for k in data:
                self._data[k] = _to_not_fetched(data[k])
        except Exception as e:
            logger.warn(f"获取群{self._group_id}中成员{self._user_id}缓存信息失败: {repr(e)}")
            user_data = get_user_info(self._user_id)
            self._data["nickname"] = user_data.nickname if user_data.nickname else NotFetched
            self._data["sex"] = user_data.sex if user_data.sex else NotFetched
            self._data["age"] = user_data.age if user_data.age else NotFetched
        super().refresh_cache()

    def __getattr__(self, item):
        if item == "_data" or item == "data":
            return self._data

        if self._data.get(item) == NotFetched or time.time() - self.last_update > expire_time:
            self.refresh_cache()

        if self._data.get(item) == NotFetched:
            return None

        if item in self._data:
            self.last_use = time.time()

        return self._data.get(item)

    def __repr__(self):
        return f"GroupMemberData(group_id={self._group_id}, user_id={self._user_id})"

    def get_nickname(self):
        """
        获取群名片（如果有群名片优先返回群名片）
        Returns:
            群名片
        """
        return self.card or self.nickname


class GroupData(QQDataItem):
    """
    QQ群数据缓存类
    """

    def __init__(
            self,
            group_id: int,
            group_name: str = NotFetched,
            member_count: int = NotFetched,
            max_member_count: int = NotFetched,
            **kwargs  # 其他字段（如实现端的 remark/description 等），将一并缓存，可通过属性访问
    ):
        super().__init__()
        self._group_id = group_id
        self._data = {
            "group_id": group_id,
            "group_name": group_name,
            "member_count": member_count,
            "max_member_count": max_member_count,
            "group_member_list": NotFetched
        }
        self.update(**kwargs)

    def refresh_cache(self):
        """
        刷新缓存
        Returns:
            None
        """
        if int(self._group_id) <= 0:
            logger.warn(f"获取群{self._group_id}缓存信息失败: group_id小于等于0")
            return
        try:
            # 不使用 no_cache: 强制刷新会绕过实现端自身的缓存, 在部分实现端上会显著变慢
            data = api.get_group_info(group_id=self._group_id)
            for k in data:
                self._data[k] = _to_not_fetched(data[k])
            self._data["group_member_list"] = NotFetched
        except Exception as e:
            logger.warn(f"获取群{self._group_id}缓存信息失败: {repr(e)}")
            return
        super().refresh_cache()

    def __getattr__(self, item):
        if item == "_data" or item == "data":
            return self._data

        if item == "group_member_list" and self._data.get(item) == NotFetched:
            try:
                res = api.get_group_member_list(self._group_id)
                member_list = [
                    GroupMemberData(
                        self._group_id,
                        member.get("user_id", 0),
                        **{k: _to_not_fetched(v) for k, v in member.items()
                           if k not in ("user_id", "group_id")}
                    )
                    for member in res
                ]
                self._data[item] = member_list
            except Exception as e:
                logger.warn(f"获取群{self._group_id}成员列表信息失败: {repr(e)}")
                return None

        if self._data.get(item) == NotFetched or time.time() - self.last_update > expire_time:
            self.refresh_cache()

        if self._data.get(item) == NotFetched:
            return None

        if item in self._data:
            self.last_use = time.time()

        return self._data.get(item)

    def __repr__(self):
        return f"GroupData(group_id={self._group_id})"


group_info = {}
group_member_info = {}
user_info = {}

group_info_lock = threading.Lock()
group_member_info_lock = threading.Lock()
user_info_lock = threading.Lock()

max_cache_size = ConfigManager.GlobalConfig().qq_data_cache.max_cache_size


def get_user_info(user_id: int, *args, **kwargs) -> UserData:
    """
    获取用户信息
    Args:
        user_id: 用户ID
    Returns:
        None
    """
    with user_info_lock:
        if user_id not in user_info:
            data = UserData(user_id, *args, **kwargs)
            user_info[user_id] = data

        data = user_info[user_id]
        return data


def get_group_info(group_id: int, *args, **kwargs) -> GroupData:
    """
    获取群信息
    Args:
        group_id: 群号
    Returns:
        None
    """
    with group_info_lock:
        if group_id not in group_info:
            data = GroupData(group_id, *args, **kwargs)
            group_info[group_id] = data

        data = group_info[group_id]
        return data


def get_group_member_info(group_id: int, user_id: int, *args, **kwargs) -> GroupMemberData:
    """
    获取群成员信息
    Args:
        group_id: 群号
        user_id: 用户ID
    Returns:
        None
    """
    with group_member_info_lock:
        if group_id not in group_member_info:
            group_member_info[group_id] = {}

        if user_id not in group_member_info[group_id]:
            data = GroupMemberData(group_id, user_id, *args, **kwargs)
            group_member_info[group_id][user_id] = data

        data = group_member_info[group_id][user_id]
        return data


def update_from_event(event_data: dict) -> None:
    """
    从事件数据中提取上游携带的信息注入缓存, 尽量避免主动调用 API 获取.

    部分实现端 (如 milky 中转层) 会在事件中携带发送者/群信息,
    直接利用这些数据填充缓存, 使后续访问 get_user_info /
    get_group_info / get_group_member_info 命中缓存而不触发 API 调用.
    Args:
        event_data: OneBot 事件数据 (原始上报 JSON)
    Returns:
        None
    """
    if not isinstance(event_data, dict):
        return
    sender = event_data.get("sender")
    if not isinstance(sender, dict) or not sender:
        return
    user_id = sender.get("user_id") or event_data.get("user_id")
    if not user_id:
        return
    user_id = int(user_id)
    group_id = event_data.get("group_id")
    group_id = int(group_id) if group_id is not None else None

    if group_id is not None:
        # 群场景: sender 通常是完整的群成员实体 (milky 等实现端携带全字段)
        member = get_group_member_info(group_id, user_id)
        member.update(**{k: v for k, v in sender.items()
                         if k not in ("user_id", "group_id")})

        # 群信息: 优先使用完整 group_info 实体, 其次使用事件平铺的标准字段
        group = get_group_info(group_id)
        group_info_data = event_data.get("group_info")
        if isinstance(group_info_data, dict):
            group.update(**{k: v for k, v in group_info_data.items() if k != "group_id"})
        else:
            group.update(**{k: v for k, v in event_data.items()
                            if k in GROUP_INFO_FIELDS})

        # 群成员实体中同时携带用户通用信息, 一并注入用户缓存
        user_fields = {k: v for k, v in sender.items() if k in USER_INFO_FIELDS}
        if user_fields:
            user = get_user_info(user_id)
            user.update(**user_fields)
    else:
        # 私聊场景: sender 即好友信息
        user = get_user_info(user_id)
        user.update(**{k: v for k, v in sender.items() if k not in ("user_id",)})
        if (event_data.get("message_type") == "private"
                and event_data.get("sub_type") == "friend"):
            # 好友私聊事件可以确认对方是好友, 避免再请求好友列表
            user.update(is_friend=True)


def garbage_collection():
    """
    垃圾回收
    Returns:
        None
    """
    counter = 0

    with group_member_info_lock:
        for k in list(group_member_info.keys()):
            group_member_items = list(zip(group_member_info[k].keys(), group_member_info[k].values()))
            max_last_use_time = max([item[1].last_use for item in group_member_items])

            if max_last_use_time < time.time() - expire_time * 2:
                del group_member_info[k]
                counter += 1
                continue

            group_member_items.sort(key=lambda x: x[1].last_use)
            if len(group_member_items) > max_cache_size * (2 / 3):
                for user_id, _ in group_member_items[:int(max_cache_size * (1 / 3))]:
                    del group_member_info[k][user_id]
                    counter += 1
            del group_member_items, max_last_use_time

    with group_info_lock:
        group_items = list(zip(group_info.keys(), group_info.values()))
        group_items.sort(key=lambda x: x[1].last_use)
        if len(group_items) > max_cache_size * (2 / 3):
            for group_id, _ in group_items[:int(max_cache_size * (1 / 3))]:
                del group_info[group_id]
                counter += 1
        del group_items

    with user_info_lock:
        user_items = list(zip(user_info.keys(), user_info.values()))
        user_items.sort(key=lambda x: x[1].last_use)
        if len(user_items) > max_cache_size * (2 / 3):
            for user_id, _ in user_items[:int(max_cache_size * (1 / 3))]:
                del user_info[user_id]
                counter += 1
        del user_items

    return counter


def scheduled_garbage_collection():
    """
    定时垃圾回收
    Returns:
        None
    """
    t = 0

    def worker():
        nonlocal t
        t += 1
        if (
                t > 4 or (t > 1 and (
                len(group_info) > max_cache_size or
                len(user_info) > max_cache_size or
                len(group_member_info) > max_cache_size
        ))):
            t = 0
            logger.debug("QQ数据缓存清理开始...")
            try:
                counter = garbage_collection()
                logger.debug(f"QQ数据缓存清理完成，共清理了 {counter} 项信息。")
            except Exception as e:
                logger.warn(f"QQ数据缓存清理时出现异常: {repr(e)}")
        TimerManager.delay(60, worker)

    worker()


# 启动垃圾回收
scheduled_garbage_collection()
