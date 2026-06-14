import boto3
import base64
import random

def create_ecommerce_infrastructure():
    """
    AWS üzerinde uçtan uca Auto Scaling ve Application Load Balancer mimarisi kuran fonksiyon.
    Bu script, us-east-1 bölgesinde çalışacak şekilde yapılandırılmıştır.
    """
    
    print("Mimarinin kurulumu başlatılıyor...\n")
    
    # İsim çakışmalarını (Duplicate Error) önlemek için rastgele 4 haneli bir ek oluşturuyoruz.
    suffix = random.randint(1000, 9999)
    
    # --- 1. Boto3 Client'larının Oluşturulması ---
    # AWS servisleriyle iletişim kurabilmek için gerekli istemcileri (client) tanımlıyoruz.
    # us-east-1 bölgesi (Kuzey Virginia) seçilmiştir.
    region = 'us-east-1'
    ec2_client = boto3.client('ec2', region_name=region)
    elbv2_client = boto3.client('elbv2', region_name=region)
    asg_client = boto3.client('autoscaling', region_name=region)
    ssm_client = boto3.client('ssm', region_name=region)
    
    # --- 2. Default VPC ve Subnet'lerin Çekilmesi ---
    print("Default VPC ve Alt Ağlar (Subnets) bulunuyor...")
    
    # Hesabımızdaki Default (Varsayılan) VPC'yi bulmak için filtreleme yapıyoruz.
    # Böylece kodu çalıştırdığınız AWS hesabında manuel VPC girmeye gerek kalmaz.
    vpc_response = ec2_client.describe_vpcs(
        Filters=[{'Name': 'isDefault', 'Values': ['true']}]
    )
    default_vpc_id = vpc_response['Vpcs'][0]['VpcId']
    print(f"Default VPC ID: {default_vpc_id}")

    # Bulduğumuz VPC içerisindeki alt ağları (Subnet'leri) çekiyoruz.
    # Load Balancer ve Auto Scaling grubumuzu bu alt ağlara yerleştireceğiz.
    subnet_response = ec2_client.describe_subnets(
        Filters=[{'Name': 'vpc-id', 'Values': [default_vpc_id]}]
    )
    # Subnet ID'lerini daha sonra kullanmak üzere bir listeye kaydediyoruz.
    subnet_ids = [subnet['SubnetId'] for subnet in subnet_response['Subnets']]
    print(f"Bulunan Subnet Sayısı: {len(subnet_ids)}")

    # --- 3. Security Group (Güvenlik Grubu) Oluşturma ---
    print("\nSecurity Group oluşturuluyor...")
    sg_name = f'ecommerce-web-sg-{suffix}'
    
    try:
        # HTTP ve SSH trafiğini yönetecek bir güvenlik duvarı oluşturuyoruz.
        sg_response = ec2_client.create_security_group(
            GroupName=sg_name,
            Description='HTTP(80) ve SSH(22) erisimine izin veren guvenlik grubu',
            VpcId=default_vpc_id
        )
        security_group_id = sg_response['GroupId']
        
        # Oluşturduğumuz gruba kuralları (Inbound Rules) ekliyoruz.
        # 80 Portu: Web sitemize internetten erişim için.
        # 22 Portu: Sunuculara terminal üzerinden SSH ile bağlanabilmek için.
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 80,
                    'ToPort': 80,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}] # 0.0.0.0/0: Herkese açık (Anywhere)
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}] # Sunucu yönetimi için SSH izni
                }
            ]
        )
        print(f"Security Group başarıyla oluşturuldu. ID: {security_group_id}")
    except Exception as e:
        print(f"Security Group hatası (Daha önceden oluşturulmuş olabilir): {e}")
        return

    # --- 4. Launch Template (Başlatma Şablonu) Oluşturma ---
    print("\nLaunch Template oluşturuluyor...")
    
    # Normalde SSM ile dinamik çekmek Best Practice'dir ancak IAM yetki hatası (AccessDenied) 
    # almamak için us-east-1 bölgesi için geçerli sabit bir Amazon Linux 2 AMI ID'si kullanıyoruz.
    # Eğer bu ID eskimişse, AWS konsolundan yeni bir AMI ID bularak burayı güncelleyebilirsiniz.
    ami_id = 'ami-0c02fb55956c7d316' # us-east-1 için Amazon Linux 2 AMI

    # Sunucu ilk defa ayağa kalktığında (Boot) otomatik çalışacak Bash scripti (UserData).
    # Apache web sunucusunu kurar ve anasayfayı oluşturur.
    user_data_script = """#!/bin/bash
yum update -y
yum install -y httpd
systemctl start httpd
systemctl enable httpd
echo '<h1>Yagmur Inan E-Ticaret Platformuna Hos Geldiniz</h1>' > /var/www/html/index.html
"""
    # UserData, AWS'ye gönderilmeden önce Base64 ile encode edilmelidir. Boto3 bunu otomatik yapmaz.
    encoded_user_data = base64.b64encode(user_data_script.encode('utf-8')).decode('utf-8')

    lt_name = f'ecommerce-launch-template-{suffix}'
    try:
        # Şablonumuzu oluşturuyoruz: t3.micro tipi (Öğrenci/Yeni hesaplar için ücretsiz katman), Amazon Linux 2 AMI ve Güvenlik Grubumuz.
        lt_response = ec2_client.create_launch_template(
            LaunchTemplateName=lt_name,
            LaunchTemplateData={
                'ImageId': ami_id,
                'InstanceType': 't3.micro',
                'SecurityGroupIds': [security_group_id],
                'UserData': encoded_user_data
            }
        )
        launch_template_id = lt_response['LaunchTemplate']['LaunchTemplateId']
        print(f"Launch Template başarıyla oluşturuldu. ID: {launch_template_id}")
    except Exception as e:
        print(f"Launch Template hatası: {e}")
        return

    # --- 5. Target Group (Hedef Grubu) Oluşturma ---
    print("\nTarget Group oluşturuluyor...")
    tg_name = f'ecommerce-target-group-{suffix}'
    
    try:
        # Load Balancer'ın trafiği dağıtacağı sunucu kümesini ve bu sunucuların sağlığını
        # nasıl kontrol edeceğini (Health Check) tanımlıyoruz.
        tg_response = elbv2_client.create_target_group(
            Name=tg_name,
            Protocol='HTTP',
            Port=80,
            VpcId=default_vpc_id,
            HealthCheckProtocol='HTTP',
            HealthCheckPort='80', # Sağlık kontrolünü 80 (HTTP) portundan yapıyoruz.
            HealthCheckPath='/',  # Ana dizini kontrol ederek sunucunun yanıt verip vermediğine bakar.
            TargetType='instance'
        )
        target_group_arn = tg_response['TargetGroups'][0]['TargetGroupArn']
        print(f"Target Group oluşturuldu. ARN: {target_group_arn}")
    except Exception as e:
        print(f"Target Group hatası: {e}")
        return

    # --- 6. Application Load Balancer (ALB) Oluşturma ---
    print("\nApplication Load Balancer oluşturuluyor...")
    alb_name = f'ecommerce-alb-{suffix}'
    
    try:
        # Kullanıcıların bağlanacağı, internete açık (internet-facing) ana yük dengeleyiciyi kuruyoruz.
        # Trafiği oluşturduğumuz alt ağlara (Subnets) dağıtacak.
        alb_response = elbv2_client.create_load_balancer(
            Name=alb_name,
            Subnets=subnet_ids,
            SecurityGroups=[security_group_id],
            Scheme='internet-facing',
            Type='application'
        )
        alb_arn = alb_response['LoadBalancers'][0]['LoadBalancerArn']
        alb_dns_name = alb_response['LoadBalancers'][0]['DNSName']
        
        # Load Balancer'a bir Listener (Dinleyici) ekliyoruz. 
        # "80 portundan gelen istekleri al, oluşturduğum Target Group'a yönlendir (forward)."
        elbv2_client.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol='HTTP',
            Port=80,
            DefaultActions=[
                {
                    'Type': 'forward',
                    'TargetGroupArn': target_group_arn
                }
            ]
        )
        print(f"Application Load Balancer oluşturuldu.")
        print(f"--> Kullanıcıların Sitenize Gireceği Adres (DNS Name): http://{alb_dns_name}")
    except Exception as e:
        print(f"ALB hatası: {e}")
        return

    # --- 7. Auto Scaling Group (Otomatik Ölçeklendirme Grubu) Oluşturma ---
    print("\nAuto Scaling Group oluşturuluyor...")
    asg_name = f'ecommerce-asg-{suffix}'
    
    try:
        # ASG'yi oluşturuyoruz. Hangi sunucu şablonunu kullanacak? (Launch Template)
        # Hangi Target Group'a sunucuları kaydedecek? (TargetGroupARNs)
        asg_client.create_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            LaunchTemplate={
                'LaunchTemplateId': launch_template_id,
                'Version': '$Latest' # Şablonun her zaman en son versiyonunu kullan.
            },
            MinSize=1,         # Minimum Kapasite: Sistemde en az 1 sunucu her zaman çalışmalı.
            MaxSize=3,         # Maksimum Kapasite: Trafik çok artarsa sistem en fazla 3 sunucuya kadar çıkabilir.
            DesiredCapacity=1, # İstenen Kapasite: Başlangıçta 1 sunucu ayağa kaldır.
            TargetGroupARNs=[target_group_arn],
            VPCZoneIdentifier=','.join(subnet_ids) # Sunucular bu alt ağlarda (subnets) açılacak.
        )
        print(f"Auto Scaling Group oluşturuldu. Adı: {asg_name}")
    except Exception as e:
        print(f"Auto Scaling Group hatası: {e}")
        return

    # --- 8. Scaling Policy (Ölçeklendirme Politikası) Ekleme ---
    print("\nÖlçeklendirme Politikası (Target Tracking) ekleniyor...")
    
    try:
        # Target Tracking (Hedef İzleme) politikası ekliyoruz. 
        # Bu politika ortalama CPU kullanımını izler. %70'i aşarsa yeni sunucu açar (Scale Out).
        # %70'in altına düştüğünde gereksiz sunucuları kapatarak maliyet tasarrufu sağlar (Scale In).
        asg_client.put_scaling_policy(
            AutoScalingGroupName=asg_name,
            PolicyName='cpu-target-tracking-policy',
            PolicyType='TargetTrackingScaling',
            TargetTrackingConfiguration={
                'PredefinedMetricSpecification': {
                    'PredefinedMetricType': 'ASGAverageCPUUtilization'
                },
                'TargetValue': 70.0 # İzlenecek hedef CPU kullanım yüzdesi (%70)
            }
        )
        print("Ölçeklendirme politikası başarıyla eklendi.")
    except Exception as e:
        print(f"Ölçeklendirme Politikası hatası: {e}")

    print("\n======================================================================")
    print("TEBRİKLER! AWS E-Ticaret Mimarisi başarıyla yapılandırıldı ve başlatıldı.")
    print("Not: Sunucunun ayağa kalkması ve Target Group tarafından 'Sağlıklı (Healthy)'")
    print("olarak işaretlenmesi 2-3 dakika sürebilir.")
    print(f"\nWeb Sitenizi Test Etmek İçin Tarayıcınızda Açın:")
    print(f"http://{alb_dns_name}")
    print("======================================================================")

if __name__ == "__main__":
    create_ecommerce_infrastructure()
