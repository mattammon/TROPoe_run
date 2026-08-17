import secrets

class VIP:
    vip_id = secrets.token_hex(2)
    def __init__(self,sfc_block=True,irs_block=True,recenter=1,
                 mwr_block=False,cbh_type=1,add_tropoe=0,
                 model_block=False,default_pres=980.0,default_cbh=2.0):

        vip_args = locals()
        self_val = vip_args.pop("self")

        self.vip_args = vip_args

        print(self.vip_args)

    def a(self,**kwargs):
        print(kwargs.get('default_pres'))
        print(default_pres)



if __name__=="__main__":
    vip = VIP()
    vip.a(**vip.vip_args)
