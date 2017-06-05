import os

from torch import optim
from torch.autograd import Variable
from torch.backends import cudnn
from torch.utils.data import DataLoader
from torchvision import transforms

from configuration import train_path, val_path, num_classes, ckpt_path, ignored_label
from datasets import VOC
from models import FCN8ResNet
from utils.loss import CrossEntropyLoss2d
from utils.training import colorize_mask, calculate_mean_iu
from utils.transforms import *

cudnn.benchmark = True


def main():
    training_batch_size = 8
    validation_batch_size = 8
    epoch_num = 200
    iter_freq_print_training_log = 250
    lr = 1e-4

    # net = FCN8ResNet(pretrained=True, num_classes=num_classes).cuda()
    # curr_epoch = 0

    net = FCN8ResNet(pretrained=False, num_classes=num_classes).cuda()
    snapshot = 'epoch_6_validation_loss_1.6566_mean_iu_0.4934.pth'
    net.load_state_dict(torch.load(os.path.join(ckpt_path, snapshot)))
    split_res = snapshot.split('_')
    curr_epoch = int(split_res[1])

    net.train()

    mean_std = ([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    simultaneous_transform = SimultaneousCompose([
        SimultaneousRandomHorizontallyFlip(),
        SimultaneousRandomCrop(320)
    ])
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(*mean_std)
    ])

    restore = transforms.Compose([
        DeNormalize(*mean_std),
        transforms.ToPILImage()
    ])

    train_set = VOC(train_path, simultaneous_transform=simultaneous_transform, transform=transform,
                    target_transform=MaskToTensor())
    train_loader = DataLoader(train_set, batch_size=training_batch_size, num_workers=8, shuffle=True)
    val_set = VOC(val_path, simultaneous_transform=simultaneous_transform, transform=transform,
                  target_transform=MaskToTensor())
    val_loader = DataLoader(val_set, batch_size=validation_batch_size, num_workers=8)

    criterion = CrossEntropyLoss2d(ignored_label=ignored_label)
    optimizer = optim.SGD(net.parameters(), lr=lr, momentum=0.9, dampening=2e-5, weight_decay=5e-4)

    if not os.path.exists(ckpt_path):
        os.mkdir(ckpt_path)

    best_val_loss = 1e9
    best_epoch = -1
    best_mean_iu = -1

    for epoch in range(curr_epoch, epoch_num):
        train(train_loader, net, criterion, optimizer, epoch, iter_freq_print_training_log)
        # if (epoch + 1) % 10 == 0:
        #     lr /= 2
        #     adjust_lr(optimizer, lr)
        val_loss, mean_iu = validate(epoch, val_loader, net, criterion, restore)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            best_mean_iu = mean_iu
            torch.save(net.state_dict(), os.path.join(
                ckpt_path, 'epoch_%d_validation_loss_%.4f_mean_iu_%.4f.pth' % (epoch + 1, val_loss, mean_iu)))
        print '--------------------------------------------------------'
        print '[validation loss %.4f]' % val_loss
        print '[best validation loss %.4f], [best_mean_iu %.4f], [best epoch %d]' % (
            best_val_loss, best_mean_iu, best_epoch + 1)
        print '--------------------------------------------------------'


def train(train_loader, net, criterion, optimizer, epoch, iter_freq_print_training_log):
    for i, data in enumerate(train_loader, 0):
        inputs, labels = data
        inputs = Variable(inputs).cuda()
        labels = Variable(labels).cuda()

        optimizer.zero_grad()
        outputs = net(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        if (i + 1) % iter_freq_print_training_log == 0:
            prediction = outputs.data.max(1)[1].squeeze_(1).cpu().numpy()
            mean_iu = calculate_mean_iu(prediction, labels.data.cpu().numpy(), num_classes)
            print '[epoch %d], [iter %d], [training batch loss %.4f], [mean_iu %.4f]' % (
                epoch + 1, i + 1, loss.data[0], mean_iu)


def validate(epoch, val_loader, net, criterion, restore):
    net.eval()
    batch_inputs = []
    batch_outputs = []
    batch_labels = []
    for vi, data in enumerate(val_loader, 0):
        inputs, labels = data
        inputs = Variable(inputs, volatile=True).cuda()
        labels = Variable(labels, volatile=True).cuda()

        outputs = net(inputs)

        batch_inputs.append(inputs.cpu())
        batch_outputs.append(outputs.cpu())
        batch_labels.append(labels.cpu())

    batch_inputs = torch.cat(batch_inputs)
    batch_outputs = torch.cat(batch_outputs)
    batch_labels = torch.cat(batch_labels)
    val_loss = criterion(batch_outputs, batch_labels)
    val_loss = val_loss.data[0]

    batch_inputs = batch_inputs.data
    batch_outputs = batch_outputs.data
    batch_labels = batch_labels.data.numpy()
    batch_prediction = batch_outputs.max(1)[1].squeeze_(1).numpy()

    mean_iu = calculate_mean_iu(batch_prediction, batch_labels, num_classes)

    to_save_dir = os.path.join(ckpt_path, str(epoch + 1))
    if not os.path.exists(to_save_dir):
        os.mkdir(to_save_dir)

    for idx, tensor in enumerate(zip(batch_inputs, batch_prediction, batch_labels)):
        pil_input = restore(tensor[0])
        pil_output = Image.fromarray(colorize_mask(tensor[1], ignored_label=ignored_label), 'RGB')
        pil_label = Image.fromarray(colorize_mask(tensor[2], ignored_label=ignored_label), 'RGB')
        pil_input.save(os.path.join(to_save_dir, '%d_img.png' % idx))
        pil_output.save(os.path.join(to_save_dir, '%d_out.png' % idx))
        pil_label.save(os.path.join(to_save_dir, '%d_label.png' % idx))

    net.train()
    return val_loss, mean_iu


if __name__ == '__main__':
    main()
