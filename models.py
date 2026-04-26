from pydantic import BaseModel
from typing import List, Dict, Self, TypeVar
from .utils import assert_type, get_dict_first_item

TModel = TypeVar("TModel")


class CategoryList(BaseModel):
    categories: List[str]

    @classmethod
    def from_yaml(cls, raw: List | Dict | str) -> Self:
        categories = []
        for item in assert_type(raw, List):
            if isinstance(item, str):
                categories.append(item)
            elif isinstance(item, dict):
                _, v = get_dict_first_item(item)
                categories.extend(cls.from_yaml(v).categories)
            else:
                raise TypeError(f"Invalid type {type(item).__name__} with value {item}")
        return cls(categories=categories)


class Prompt(BaseModel):
    category: str = "uncategorized"
    prompt: str = ""
