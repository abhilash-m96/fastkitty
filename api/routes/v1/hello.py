from fastapi import APIRouter, Depends
from api.deps import get_db, get_tenant_id
from models.posts import BlogPost


router = APIRouter(tags=["Hello"])


@router.get("/hello")
async def hello(tenant_id: str = Depends(get_tenant_id)):
    return {"message": f"Hello {tenant_id}!"}


@router.get("/blog-posts")
async def blog_posts(db=Depends(get_db)):
    import pdb

    pdb.set_trace()

    posts = db.query(BlogPost).all()
    return posts
